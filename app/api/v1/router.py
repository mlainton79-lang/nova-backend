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
from app.api.v1.endpoints import daily_review
router.include_router(daily_review.router, tags=["daily_review"])
from app.api.v1.endpoints import diary
router.include_router(diary.router, tags=["diary"])
from app.api.v1.endpoints import budget
router.include_router(budget.router, tags=["budget"])
from app.api.v1.endpoints import multi_agent
router.include_router(multi_agent.router, tags=["multi_agent"])
from app.api.v1.endpoints import skill_learner
router.include_router(skill_learner.router, tags=["skill_learner"])
from app.api.v1.endpoints import agentic
router.include_router(agentic.router, tags=["agentic"])
from app.api.v1.endpoints import self_goals
router.include_router(self_goals.router, tags=["self_goals"])
from app.api.v1.endpoints import retrieval
router.include_router(retrieval.router, tags=["retrieval"])
from app.api.v1.endpoints import outcomes
router.include_router(outcomes.router, tags=["outcomes"])
from app.api.v1.endpoints import artifacts
router.include_router(artifacts.router, tags=["artifacts"])
from app.api.v1.endpoints import repo_intel
router.include_router(repo_intel.router, tags=["repo_intel"])
from app.api.v1.endpoints import handover
router.include_router(handover.router, tags=["handover"])
from app.api.v1.endpoints import transcription
router.include_router(transcription.router, tags=["transcription"])
from app.api.v1.endpoints import vinted
router.include_router(vinted.router, tags=["vinted"])
from app.api.v1.endpoints import whatsapp
router.include_router(whatsapp.router, tags=["whatsapp"])
from app.api.v1.endpoints import banking
router.include_router(banking.router, tags=["banking"])
from app.api.v1.endpoints import email_agent
router.include_router(email_agent.router, tags=["email_agent"])
from app.api.v1.endpoints import codebase
router.include_router(codebase.router, tags=["codebase"])
from app.api.v1.endpoints import admin_clear
router.include_router(admin_clear.router, tags=["admin"])
from app.api.v1.endpoints import evals
router.include_router(evals.router, tags=["evals"])
from app.api.v1.endpoints import tasks
router.include_router(tasks.router, tags=["tasks"])
from app.api.v1.endpoints import skills
router.include_router(skills.router, tags=["skills"])
from app.api.v1.endpoints import video
router.include_router(video.router, tags=["video"])
from app.api.v1.endpoints import facts
router.include_router(facts.router, tags=["facts"])
from app.api.v1.endpoints import email_triage
router.include_router(email_triage.router, tags=["triage"])
from app.api.v1.endpoints import health_dashboard
router.include_router(health_dashboard.router, tags=["health"])
from app.api.v1.endpoints import self_improvement
router.include_router(self_improvement.router, tags=["self_improvement"])
from app.api.v1.endpoints import fabrication
router.include_router(fabrication.router, tags=["fabrication"])
from app.api.v1.endpoints import expenses
router.include_router(expenses.router, tags=["expenses"])

# ── Startup initialisations (one each, no duplicates) ──────────────────────
try:
    init_gmail_tables()
except Exception as e:
    print(f"[ROUTER] Gmail table init failed: {e}")

try:
    init_rag_tables()
    print("[ROUTER] RAG tables ready")
except Exception as e:
    print(f"[ROUTER] RAG table init failed (non-fatal): {e}")

_inits = [
    ("app.core.news_monitor",           "init_news_tables",           "News"),
    ("app.core.goals",                  "init_goals_table",           "Goals"),
    ("app.core.emotional_intelligence", "init_emotional_tables",      "EI"),
    ("app.core.proactive",              "init_proactive_tables",      "Proactive"),
    ("app.core.world_model",            "init_world_model",           "World model"),
    ("app.core.capabilities",           "init_capabilities_table",    "Capabilities"),
    ("app.core.email_drafter",          "init_draft_tables",          "Email drafter"),
    ("app.core.self_eval",              "init_eval_tables",           "Self-eval"),
    ("app.core.episodic_memory",        "init_episodic_tables",       "Episodic memory"),
    ("app.core.semantic_memory",        "init_semantic_memory_tables","Semantic memory"),
    ("app.core.learning",               "init_learning_tables",       "Learning"),
    ("app.core.knowledge_base",         "init_knowledge_base",        "Knowledge base"),
    ("app.core.living_memory",          "init_living_memory_tables",  "Living memory"),
    ("app.core.open_banking",           "init_banking_tables",        "Banking"),
    ("app.core.youtube_monitor",        "init_youtube_tables",        "YouTube"),
    ("app.core.correspondence",         "init_correspondence_tables", "Correspondence"),
    ("app.core.pattern_recognition",    "init_pattern_tables",        "Patterns"),
    ("app.core.tony_journal",           "init_journal_tables",        "Journal"),
    ("app.core.tony_architect",         "init_architect_tables",      "Architect"),
    ("app.core.email_agent",            "init_email_agent_tables",    "Email agent"),
    ("app.core.financial_intelligence", "init_financial_tables",      "Financial intel"),
    ("app.core.codebase_sync",          "init_codebase_table",        "Codebase"),
    ("app.core.topic_bans",             "init_topic_bans_table",      "Topic bans"),
    ("app.core.gap_detector",           "init_gap_tables",            "Capability gap detector"),
    ("app.core.task_queue",             "init_task_queue_tables",     "Task queue"),
    ("app.skills.loader",               "register_skills_in_db",      "Skills registry"),
    ("app.core.fact_extractor",         "init_fact_tables",           "Fact extractor"),
    ("app.core.email_triage",           "init_triage_tables",         "Email triage"),
    ("app.core.self_improvement",       "init_self_improvement_tables", "Self-improvement"),
    ("app.core.fabrication_detector",   "init_fabrication_tables",    "Fabrication detector"),
    ("app.core.receipt_extractor",      "init_expense_tables",        "Expense tracker"),
    ("app.core.document_memory",        "init_document_memory_tables","Document memory"),
    ("app.core.tony_diary",             "init_diary_tables",          "Tony's diary"),
    ("app.core.budget_guard",           "init_budget_tables",         "Budget guard"),
    ("app.core.skill_learner",          "init_skill_proposal_tables", "Skill learner"),
    ("app.core.tony_self_goals",        "init_self_goals_tables",     "Tony self-goals"),
    ("app.core.outcome_tracker",        "init_outcome_tables",        "Outcome tracker"),
    ("app.core.known_facts_seed",       "seed_bedrock_facts",         "Bedrock facts"),
    ("app.core.repository_intelligence","init_repo_intel_tables",     "Repo intelligence"),
    ("app.core.register_new_capabilities", "register_all",            "New capabilities registry"),
]

for module_path, fn_name, label in _inits:
    try:
        import importlib
        mod = importlib.import_module(module_path)
        getattr(mod, fn_name)()
    except Exception as e:
        print(f"[{label.upper()}] Init failed: {e}")
