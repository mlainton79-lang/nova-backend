from fastapi import APIRouter
from app.api.v1.endpoints import health, chat, chat_stream, council
from app.api.v1.endpoints import gmail
from app.api.v1.endpoints import cases
from app.core.gmail_service import init_gmail_tables
from app.core.rag import init_rag_tables

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(chat.router, tags=["chat"])
router.include_router(chat_stream.router, tags=["chat"])
router.include_router(council.router, tags=["council"])
router.include_router(gmail.router, tags=["gmail"])
router.include_router(cases.router, tags=["cases"])

# Initialise tables on startup
try:
    init_gmail_tables()
except Exception as e:
    print(f"[ROUTER] Gmail table init failed: {e}")

try:
    init_rag_tables()
except Exception as e:
    print(f"[ROUTER] RAG table init failed: {e}")
