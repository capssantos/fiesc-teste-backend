from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FIESC Predictive Maintenance API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/fiesc_predictive"
    database_connect_timeout_seconds: int = 5
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://fiesc.carlosp.dev"
    cors_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    auto_migrate_on_startup: bool = True

    storage_backend: str = "minio"
    s3_endpoint_url: str | None = None
    s3_public_base_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_documents_bucket: str = "fiesc-documents"
    s3_artifacts_bucket: str = "fiesc-analysis-artifacts"
    s3_presigned_expiry_seconds: int = 3600
    minio_console_url: str | None = None

    llm_provider: str | None = None
    ollama_model: str | None = None
    ollama_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str = "https://api.openai.com"

    similarity_k: int = 10
    similarity_metric: str = "euclidean"
    max_upload_size_mb: int = 10
    allowed_document_extensions: str = ".pdf,.txt,.md,.docx"
    fault_document_map_path: str = str(BACKEND_ROOT / "config" / "fault_document_map.yaml")
    dataset_path: str = str(BACKEND_ROOT / "docs" / "banner.csv")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"dev", "development"}:
                return True
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_extensions(self) -> set[str]:
        return {value.strip().lower() for value in self.allowed_document_extensions.split(",") if value.strip()}

    @property
    def storage_configured(self) -> bool:
        if self.storage_backend.lower() != "minio":
            return False
        return bool(
            self.s3_endpoint_url
            and self.s3_access_key
            and self.s3_secret_key
            and self.s3_documents_bucket
            and self.s3_artifacts_bucket
        )

    @property
    def effective_llm_provider(self) -> str | None:
        if self.llm_provider:
            return self.llm_provider.lower()
        if self.openai_api_key and self.openai_model:
            return "openai"
        if self.ollama_model and self.ollama_base_url:
            return "ollama"
        return None

    @property
    def llm_configured(self) -> bool:
        provider = self.effective_llm_provider
        if not provider:
            return False
        if provider == "ollama":
            return bool(self.ollama_model and self.ollama_base_url)
        if provider == "openai":
            return bool(self.openai_model and self.openai_api_key and self.openai_base_url)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
