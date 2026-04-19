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
from app.api.v1.endpoints import proactive_alerts
router.include_router(proactive_alerts.router, tags=["proactive_alerts"])

from app.api.v1.endpoints import builder
router.include_router(builder.router, tags=["builder"])
from app.api.v1.endpoints import vision
router.include_router(vision.router, tags=["vision"])
from app.api.v1.endpoints import proactive
router.include_router(proactive.router, tags=["proactive"])
from app.api.v1.endpoints import calendar
router.include_router(calendar.router, tags=["calendar"])
from app.api.v1.endpoints import goals
router.include_router(goals.router, tags=["goals"])
from app.api.v1.endpoints import push
router.include_router(push.router, tags=["push"])
from app.api.v1.endpoints import monitor
router.include_router(monitor.router, tags=["monitor"])
from app.api.v1.endpoints import voice
router.include_router(voice.router, tags=["voice"])
from app.api.v1.endpoints import drafts
router.include_router(drafts.router, tags=["drafts"])
from app.api.v1.endpoints import documents
router.include_router(documents.router, tags=["documents"])
from app.api.v1.endpoints import handover
router.include_router(handover.router, tags=["handover"])
from app.api.v1.endpoints import transcription
router.include_router(transcription.router, tags=["voice"])
from app.api.v1.endpoints import vinted
router.include_router(vinted.router, tags=["vinted"])
from app.api.v1.endpoints import whatsapp
router.include_router(whatsapp.router, tags=["whatsapp"])
from app.api.v1.endpoints import banking
router.include_router(banking.router, tags=["banking"])
from app.api.v1.endpoints import cases
router.include_router(cases.router, tags=["cases"])

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

# Initialise news monitor
try:
    from app.core.news_monitor import init_news_tables
    init_news_tables()
except Exception as e:
    print(f"[ROUTER] News init failed: {e}")

# Initialise goals system
try:
    from app.core.goals import init_goals_table
    init_goals_table()
except Exception as e:
    print(f"[ROUTER] Goals init failed: {e}")

# Initialise emotional intelligence
try:
    from app.core.emotional_intelligence import init_emotional_tables
    init_emotional_tables()
except Exception as e:
    print(f"[ROUTER] EI init failed: {e}")

# Initialise proactive system
try:
    from app.core.proactive import init_proactive_tables
    init_proactive_tables()
except Exception as e:
    print(f"[ROUTER] Proactive init failed: {e}")

# Initialise world model
try:
    from app.core.world_model import init_world_model
    init_world_model()
except Exception as e:
    print(f"[ROUTER] World model init failed: {e}")

# Initialise capabilities registry
try:
    from app.core.capabilities import init_capabilities_table
    init_capabilities_table()
except Exception as e:
    print(f"[ROUTER] Capabilities init failed: {e}")

# Initialise email drafter
try:
    from app.core.email_drafter import init_draft_tables
    init_draft_tables()
except Exception as e:
    print(f"[ROUTER] Email drafter init failed: {e}")

# Initialise self-eval
try:
    from app.core.self_eval import init_eval_tables
    init_eval_tables()
except Exception as e:
    print(f"[ROUTER] Self-eval init failed: {e}")

# Initialise episodic memory
try:
    from app.core.episodic_memory import init_episodic_tables
    init_episodic_tables()
except Exception as e:
    print(f"[ROUTER] Episodic memory init failed: {e}")

# Initialise semantic memory
try:
    from app.core.semantic_memory import init_semantic_memory_tables
    init_semantic_memory_tables()
except Exception as e:
    print(f"[ROUTER] Semantic memory init failed: {e}")

# Initialise learning loop
try:
    from app.core.learning import init_learning_tables
    init_learning_tables()
except Exception as e:
    print(f"[ROUTER] Learning init failed: {e}")

# Initialise proactive intelligence
try:
    from app.core.proactive_intelligence import init_proactive_intelligence_tables
    init_proactive_intelligence_tables()
except Exception as e:
    print(f"[ROUTER] Proactive intelligence init failed: {e}")

# Initialise knowledge base
try:
    from app.core.knowledge_base import init_knowledge_base
    init_knowledge_base()
except Exception as e:
    print(f"[ROUTER] Knowledge base init failed: {e}")

# Initialise living memory
try:
    from app.core.living_memory import init_living_memory_tables
    init_living_memory_tables()
except Exception as e:
    print(f"[ROUTER] Living memory init failed: {e}")

# Initialise open banking
try:
    from app.core.open_banking import init_banking_tables
    init_banking_tables()
except Exception as e:
    print(f"[ROUTER] Banking init failed: {e}")

# Initialise YouTube monitor
try:
    from app.core.youtube_monitor import init_youtube_tables
    init_youtube_tables()
except Exception as e:
    print(f"[ROUTER] YouTube monitor init failed: {e}")

# Initialise correspondence tables
try:
    from app.core.correspondence import init_correspondence_tables
    init_correspondence_tables()
except Exception as e:
    print(f"[ROUTER] Correspondence init failed: {e}")

# Initialise pattern recognition
try:
    from app.core.pattern_recognition import init_pattern_tables
    init_pattern_tables()
except Exception as e:
    print(f"[ROUTER] Pattern recognition init failed: {e}")

# Initialise Tony's journal
try:
    from app.core.tony_journal import init_journal_tables
    init_journal_tables()
except Exception as e:
    print(f"[ROUTER] Journal init failed: {e}")

# Initialise Tony's architecture model
try:
    from app.core.tony_architect import init_architect_tables
    init_architect_tables()
except Exception as e:
    print(f"[ROUTER] Architect init failed: {e}")

# Initialise email agent
try:
    from app.core.email_agent import init_email_agent_tables
    init_email_agent_tables()
except Exception as e:
    print(f"[ROUTER] Email agent init failed: {e}")

# Initialise financial intelligence
try:
    from app.core.financial_intelligence import init_financial_tables
    init_financial_tables()
except Exception as e:
    print(f"[ROUTER] Financial intelligence init failed: {e}")

# Initialise learning engine
try:
    from app.core.learning import init_learning_tables
    init_learning_tables()
except Exception as e:
    print(f"[ROUTER] Learning init failed: {e}")

# Initialise episodic memory
try:
    from app.core.episodic_memory import init_episodic_tables
    init_episodic_tables()
except Exception as e:
    print(f"[EPISODIC] Init failed: {e}")

# Initialise world model
try:
    from app.core.world_model import init_world_model
    init_world_model()
except Exception as e:
    print(f"[WORLD_MODEL] Init failed: {e}")

# Initialise knowledge base
try:
    from app.core.knowledge_base import init_knowledge_base
    init_knowledge_base()
except Exception as e:
    print(f"[KNOWLEDGE] Init failed: {e}")

from app.api.v1.endpoints import email_agent
router.include_router(email_agent.router, tags=["email_agent"])
