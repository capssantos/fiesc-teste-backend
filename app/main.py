from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys

if __package__ in {None, ""}:
    backend_root = Path(__file__).resolve().parents[1]
    backend_root_str = str(backend_root)
    if backend_root_str not in sys.path:
        sys.path.insert(0, backend_root_str)

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.services.migration import run_db_migrations
from app.services.object_storage import ensure_buckets


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_migrate_on_startup:
        try:
            run_db_migrations()
        except Exception as exc:
            logger.exception("Database migration failed on startup: %s", exc)
            raise

    try:
        ensure_buckets()
    except Exception as exc:
        logger.warning("Object storage startup check failed: %s", exc)
    yield


fastapi_app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

fastapi_app.include_router(api_router, prefix=settings.api_v1_prefix)


@fastapi_app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Erro na requisicao."

    mapped_messages = {
        "object_storage_not_configured": "Object storage nao configurado. Revise as variaveis S3/MinIO no .env.",
        "object_storage_access_denied": "Object storage recusou acesso. Revise endpoint, access key, secret key e bucket.",
        "object_storage_unavailable": "Object storage indisponivel no momento.",
        "object_storage_upload_failed": "Falha ao enviar arquivo para o object storage.",
        "object_storage_presign_failed": "Falha ao gerar link de download do object storage.",
        "object_storage_bucket_create_failed": "Falha ao criar bucket no object storage.",
        "unsupported_file_type": "Tipo de arquivo nao suportado.",
        "file_too_large": "Arquivo maior que o limite permitido.",
    }

    if isinstance(detail, str) and detail in mapped_messages:
        message = mapped_messages[detail]

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "message": message,
            "detail": detail,
        },
    )


@fastapi_app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_, exc: RequestValidationError):
    errors = exc.errors()

    friendly_errors: list[dict[str, object]] = []
    malformed_json = False

    for error in errors:
        location = ".".join(str(item) for item in error.get("loc", []) if item != "body")
        error_type = error.get("type", "validation_error")
        input_value = error.get("input")

        if error_type == "json_invalid":
            malformed_json = True
            friendly_errors.append(
                {
                    "field": location or "body",
                    "message": "JSON invalido. Revise virgulas, aspas, chaves e o formato geral do body.",
                }
            )
            continue

        if location.endswith("created_at"):
            friendly_errors.append(
                {
                    "field": "created_at",
                    "message": (
                        "Data/hora invalida. Use algo como 2026-06-01T21:32:53.911176+00:00 "
                        "ou 2026-06-01 21:32:53+00:00."
                    ),
                    "received": input_value,
                }
            )
            continue

        if error_type == "extra_forbidden":
            friendly_errors.append(
                {
                    "field": location or "body",
                    "message": "Campo nao permitido para este endpoint.",
                    "received": input_value,
                }
            )
            continue

        friendly_errors.append(
            {
                "field": location or "body",
                "message": error.get("msg", "Erro de validacao."),
                "received": input_value,
            }
        )

    message = (
        "Body JSON invalido." if malformed_json else "Payload invalido. Revise os campos enviados e tente novamente."
    )

    return JSONResponse(
        status_code=422,
        content={
            "message": message,
            "errors": friendly_errors,
            "hint": {
                "content_type": "application/json",
                "created_at_example": "2026-06-01T21:32:53.911176+00:00",
                "accepted_identifier_fields": ["id", "source_event_id"],
            },
        },
    )


@fastapi_app.get("/")
def root() -> dict[str, str]:
    return {"app": settings.app_name, "api_prefix": settings.api_v1_prefix, "docs": "/docs"}


app = CORSMiddleware(
    fastapi_app,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
