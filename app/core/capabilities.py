"""
Tony's capability registry.
Tracks what Tony can and can't do.
When a request hits an unknown capability, Tony researches and proposes a build.
"""
import psycopg2
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
    if status:
        cur.execute("SELECT name, description, status, endpoint FROM capabilities WHERE status=%s ORDER BY name", (status,))
    else:
        cur.execute("SELECT name, description, status, endpoint FROM capabilities ORDER BY status, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"name": r[0], "description": r[1], "status": r[2], "endpoint": r[3]} for r in rows]

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
