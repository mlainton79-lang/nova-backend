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
from app.api.v1.endpoints import capabilities
router.include_router(capabilities.router, tags=["capabilities"])
from app.api.v1.endpoints import agent
router.include_router(agent.router, tags=["agent"])
from app.api.v1.endpoints import builder
router.include_router(builder.router, tags=["builder"])
from app.api.v1.endpoints import vision
router.include_router(vision.router, tags=["vision"])
from app.api.v1.endpoints import proactive
router.include_router(proactive.router, tags=["proactive"])
from app.api.v1.endpoints import calendar
router.include_router(calendar.router, tags=["calendar"])

# Initialise tables on startup
try:
    init_gmail_tables()
except Exception as e:
    print(f"[ROUTER] Gmail table init failed: {e}")

try:
    init_rag_tables()
    print("[ROUTER] RAG tables ready")
except Exception as e:
    print(f"[ROUTER] RAG table init failed (non-fatal): {e}")

# Initialise proactive system
try:
    from app.core.proactive import init_proactive_tables
    init_proactive_tables()
except Exception as e:
    print(f"[ROUTER] Proactive init failed: {e}")

# Initialise world model
try:
    from app.core.world_model import init_world_model_table
    init_world_model_table()
except Exception as e:
    print(f"[ROUTER] World model init failed: {e}")

# Initialise capabilities registry
try:
    from app.core.capabilities import init_capabilities_table
    init_capabilities_table()
except Exception as e:
    print(f"[ROUTER] Capabilities init failed: {e}")
