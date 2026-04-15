from fastapi import APIRouter
from app.api.v1.endpoints import health, chat, chat_stream

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(chat.router, tags=["chat"])
router.include_router(chat_stream.router, tags=["chat"])
