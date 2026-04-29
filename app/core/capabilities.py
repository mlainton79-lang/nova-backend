"""
Tony's capability registry.
Tracks what Tony can and can't do.
When a request hits an unknown capability, Tony researches and proposes a build.
"""
import psycopg2
import psycopg2.extras
import os
from datetime import datetime

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")

def init_capabilities_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
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
        # N1.1: idempotent column additions for richer capability metadata
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS risk_level TEXT DEFAULT 'low'")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS approval_required BOOLEAN DEFAULT false")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS cost_type TEXT DEFAULT 'free'")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS runner TEXT")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS inputs JSONB")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS outputs JSONB")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS last_tested TIMESTAMP")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS last_result TEXT")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS failure_notes TEXT")
        cur.execute("ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS capability_gaps (
                id SERIAL PRIMARY KEY,
                request TEXT NOT NULL,
                proposed_solution TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()

        # Seed with Tony's known capabilities
        capabilities = [
            ("chat", "Multi-provider chat with Claude, Gemini, Groq, Mistral, OpenRouter, DeepSeek", "active", "/api/v1/chat/stream"),
            ("council", "Multi-brain deliberation across 8 providers", "active", "/api/v1/council"),
            ("memory", "Persistent memory storage and injection", "active", "/api/v1/memories"),
            ("gmail_read", "Read and search emails across 4 accounts", "active", "/api/v1/gmail/emails"),
            ("gmail_send", "Send emails from any connected account", "active", "/api/v1/gmail/send"),
            ("gmail_morning", "Morning email summary", "active", "/api/v1/gmail/morning"),
            ("case_builder", "RAG legal case builder from emails", "active", "/api/v1/cases/build"),
            ("case_search", "Semantic search within a case", "active", "/api/v1/cases/query"),
            ("vision", "Camera vision - read photos and documents", "active", "/api/v1/chat/stream"),
            ("brave_search", "Web search via Brave API", "active", "injected"),
            ("file_reading", "Read PDFs, Word, Excel, CSV, TXT", "active", "injected"),
            ("codebase_awareness", "Read and understand Nova's own code", "active", "/api/v1/codebase"),
            ("autonomous_push", "Push code changes to GitHub", "active", "/api/v1/auto-push"),
            ("self_knowledge", "Tony's self-knowledge database", "active", "/api/v1/self-knowledge"),
            ("think_sessions", "Tony's reasoning logs", "active", "/api/v1/think-sessions"),
            ("health_check", "Backend health monitoring", "active", "/api/v1/health"),
            ("self_improvement_loop", "48-hour autonomous check and improve cycle", "active", "/internal/trigger-self-improvement"),
            ("vision_video", "Watch YouTube videos, study transcripts, research topics by video", "active", "/api/v1/vision/watch"),
            ("vision_image", "See and analyse images, read scanned documents", "active", "/api/v1/vision/see"),
            ("calendar", "Google Calendar read/write - today's schedule, upcoming events, create events", "active", "/api/v1/calendar/today"),
            ("facebook", "Facebook posting and reading", "not_built", None),
            ("vinted", "Vinted listing creation", "not_built", None),
            ("ebay", "eBay listing creation", "not_built", None),
            ("whatsapp", "WhatsApp messaging", "not_built", None),
            ("sms", "SMS sending", "not_built", None),
            ("phone_calls", "Make or transcribe phone calls", "not_built", None),
            ("spotify", "Spotify playback control", "not_built", None),
            ("youtube", "YouTube search and monitoring", "not_built", None),
            ("shopify", "Shopify store management", "not_built", None),
            ("ocr_vision", "OCR on scanned PDFs and images", "not_built", None),
            ("browser_automation", "Autonomous web browsing and form filling", "not_built", None),
            ("notification_push", "Push notifications to your phone", "not_built", None),
            ("voice_output", "Tony speaks responses aloud", "not_built", None),
        ]

        for name, desc, status, endpoint in capabilities:
            cur.execute("""
                INSERT INTO capabilities (name, description, status, endpoint)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO NOTHING
            """, (name, desc, status, endpoint))

        conn.commit()
        cur.close()
        conn.close()
        print("[CAPABILITIES] Registry initialised")
    except Exception as e:
        print(f"[CAPABILITIES] Init failed: {e}")

def get_capabilities(status=None):
    conn = get_conn()
    cur = conn.cursor()
    select_cols = (
        "name, description, status, endpoint, runner, "
        "risk_level, approval_required, cost_type, "
        "inputs, outputs, last_tested, last_result, failure_notes, "
        "notes, added_at, updated_at"
    )
    if status:
        cur.execute(f"SELECT {select_cols} FROM capabilities WHERE status=%s ORDER BY name", (status,))
    else:
        cur.execute(f"SELECT {select_cols} FROM capabilities ORDER BY status, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "name": r[0],
            "description": r[1],
            "status": r[2],
            "endpoint": r[3],
            "runner": r[4],
            "risk_level": r[5],
            "approval_required": r[6],
            "cost_type": r[7],
            "inputs": r[8],
            "outputs": r[9],
            "last_tested": r[10].isoformat() if r[10] else None,
            "last_result": r[11],
            "failure_notes": r[12],
            "notes": r[13],
            "added_at": r[14].isoformat() if r[14] else None,
            "updated_at": r[15].isoformat() if r[15] else None,
        }
        for r in rows
    ]

def log_capability_gap(request_text, proposed_solution=None):
    """Log when Tony encounters something he can't do."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO capability_gaps (request, proposed_solution) VALUES (%s, %s)",
            (request_text[:500], proposed_solution)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[CAPABILITIES] Gap log failed: {e}")

def get_capability_summary():
    """Get a summary string for Tony's system prompt."""
    try:
        caps = get_capabilities()
        active = [c["name"] for c in caps if c["status"] == "active"]
        not_built = [c["name"] for c in caps if c["status"] == "not_built"]
        return f"ACTIVE CAPABILITIES: {', '.join(active)}\nNOT YET BUILT: {', '.join(not_built)}"
    except Exception:
        return ""


def update_capability(name: str, **fields) -> bool:
    """
    Update a capability by name. Whitelisted columns only.
    Returns True if a row was updated, False if name not found.
    """
    allowed = {
        "status", "endpoint", "runner",
        "risk_level", "approval_required", "cost_type",
        "inputs", "outputs",
        "last_tested", "last_result", "failure_notes",
        "notes", "description"
    }
    set_fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not set_fields:
        return False

    set_clause = ", ".join(f"{k} = %s" for k in set_fields.keys())
    set_clause += ", updated_at = NOW()"
    values = list(set_fields.values()) + [name]

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE capabilities SET {set_clause} WHERE name = %s",
                    values
                )
                return cur.rowcount > 0
    finally:
        conn.close()


def create_capability(name: str, description: str, status: str = "active", **kw) -> int:
    """
    Create a new capability. Raises psycopg2.IntegrityError on duplicate name.
    Returns new row id.
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO capabilities (
                        name, description, status, endpoint, runner,
                        risk_level, approval_required, cost_type,
                        inputs, outputs, notes, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id
                """, (
                    name, description, status,
                    kw.get("endpoint"), kw.get("runner"),
                    kw.get("risk_level", "low"),
                    kw.get("approval_required", False),
                    kw.get("cost_type", "free"),
                    psycopg2.extras.Json(kw["inputs"]) if kw.get("inputs") else None,
                    psycopg2.extras.Json(kw["outputs"]) if kw.get("outputs") else None,
                    kw.get("notes")
                ))
                return cur.fetchone()[0]
    finally:
        conn.close()


def upsert_capability(name: str, description: str, status: str = "active", **kw) -> int:
    """
    Insert or update a capability. Used by seed scripts.
    Returns row id.
    """
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO capabilities (
                        name, description, status, endpoint, runner,
                        risk_level, approval_required, cost_type,
                        inputs, outputs, notes, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (name) DO UPDATE SET
                        description = EXCLUDED.description,
                        status = EXCLUDED.status,
                        endpoint = EXCLUDED.endpoint,
                        runner = EXCLUDED.runner,
                        risk_level = EXCLUDED.risk_level,
                        approval_required = EXCLUDED.approval_required,
                        cost_type = EXCLUDED.cost_type,
                        inputs = EXCLUDED.inputs,
                        outputs = EXCLUDED.outputs,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                    RETURNING id
                """, (
                    name, description, status,
                    kw.get("endpoint"), kw.get("runner"),
                    kw.get("risk_level", "low"),
                    kw.get("approval_required", False),
                    kw.get("cost_type", "free"),
                    psycopg2.extras.Json(kw["inputs"]) if kw.get("inputs") else None,
                    psycopg2.extras.Json(kw["outputs"]) if kw.get("outputs") else None,
                    kw.get("notes")
                ))
                return cur.fetchone()[0]
    finally:
        conn.close()
