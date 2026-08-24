from fastapi import APIRouter

from app.api.routes import analyses, chat, documents, events, faults, health


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(analyses.router)
api_router.include_router(events.router)
api_router.include_router(faults.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
