"""
Register capabilities built this session into the registry.

R2.1 (2026-06-01): rewritten to go through the canonical upsert_capability
facade in app.core.capabilities, which writes to tony_capabilities. The
prior version of this module wrote raw SQL into the unprefixed legacy
`capabilities` table — that path is now dead. Same NEW_CAPABILITIES
catalog as before; only the write target changed.
"""
from app.core.capabilities import upsert_capability


NEW_CAPABILITIES = [
    ("evals",              "Regression test suite — 16 cases across voice, topic-isolation, honesty, fabrication, grief, commands", "active", "/api/v1/evals/run"),
    ("task_queue",         "Postgres-backed persistent queue for long-horizon background work",                   "active", "/api/v1/tasks"),
    ("skills",             "Modular capability bundles (SKILL.md) with progressive disclosure",                    "active", "/api/v1/skills"),
    ("fact_extractor",     "Mem0-style structured fact extraction from conversations",                              "active", "/api/v1/facts"),
    ("email_triage",       "LLM-based email categorisation, urgency, drafted replies",                             "active", "/api/v1/triage/digest"),
    ("photo_to_video",     "ffmpeg-based reel/short generation from photos for Vinted/Reels/Shorts",              "active", "/api/v1/video/photos_to_reel"),
    ("eval_gate",          "Post-deploy safety check with auto-revert on critical regressions",                    "active", "internal"),
    ("runtime_check",      "Runtime import validation before autonomous code pushes",                              "active", "internal"),
    ("self_improvement",   "Auto-proposes rule/prompt changes from eval failures",                                 "active", "/api/v1/self_improvement/proposals"),
    ("health_dashboard",   "Single-endpoint system health snapshot",                                               "active", "/api/v1/health/dashboard"),
    ("smart_briefing",     "LLM-synthesised intelligent morning brief (one paragraph)",                            "active", "/api/v1/proactive/briefing/smart"),
    ("goal_planner",       "R2.2 — Decompose a stated goal into ordered steps with registry + governor checks. Produces plans; does not execute.", "active", "/api/v1/planner/plan"),
]


def register_all():
    """Upsert every capability in NEW_CAPABILITIES through the canonical
    facade. Idempotent — re-runs update the description/status/endpoint
    rather than creating duplicates (UNIQUE on capability_key).
    """
    try:
        for name, desc, status, endpoint in NEW_CAPABILITIES:
            upsert_capability(
                name=name,
                description=desc,
                status=status,
                endpoint=endpoint,
                source="register_new_capabilities.register_all",
            )
        print(f"[CAPABILITIES] Registered {len(NEW_CAPABILITIES)} new capabilities")
    except Exception as e:
        print(f"[CAPABILITIES] Register failed: {e}")
