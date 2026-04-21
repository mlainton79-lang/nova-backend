"""
Register capabilities built this session into the registry.
Run once at startup to make sure Tony knows what he can actually do.
"""
import os
import psycopg2


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


NEW_CAPABILITIES = [
    ("evals",              "Regression test suite — 14 cases across voice, CCJ, gap detection, honesty, length", "active", "/api/v1/evals/run"),
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
]


def register_all():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        # Make sure the capabilities table has ON CONFLICT support
        cur.execute("""
            CREATE TABLE IF NOT EXISTS capabilities (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                endpoint TEXT,
                added_at TIMESTAMP DEFAULT NOW(),
                notes TEXT
            )
        """)
        for name, desc, status, endpoint in NEW_CAPABILITIES:
            cur.execute("""
                INSERT INTO capabilities (name, description, status, endpoint)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    endpoint = EXCLUDED.endpoint
            """, (name, desc, status, endpoint))
        cur.close()
        conn.close()
        print(f"[CAPABILITIES] Registered {len(NEW_CAPABILITIES)} new capabilities")
    except Exception as e:
        print(f"[CAPABILITIES] Register failed: {e}")
