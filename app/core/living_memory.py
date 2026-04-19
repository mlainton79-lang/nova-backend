"""
Tony's Living Memory.

An always-current, structured picture of Matthew's life
across 11 key dimensions. Updated after every significant conversation.

This is what makes Tony feel like he genuinely knows Matthew —
not just facts retrieved from a database, but an integrated
understanding of who he is and what's happening in his life right now.

Sections:
1. LIFE_SUMMARY — one paragraph summary of Matthew's current situation
2. CURRENT_FOCUS — what Matthew is focused on right now
3. OPEN_LOOPS — things mentioned but not resolved
4. RECENT_EVENTS — significant things that happened recently
5. FINANCIAL — financial situation and trajectory
6. LEGAL — legal situation (Western Circle, CCJ)
7. FAMILY — family context (Georgina, Amelia, Margot)
8. WORK — work context (Sid Bailey)
9. HEALTH — physical and mental wellbeing signals
10. GOALS — active goals and progress
11. WEEKLY_STRATEGY — Tony's strategic assessment this week
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict, Optional
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


SECTIONS = [
    "LIFE_SUMMARY", "CURRENT_FOCUS", "OPEN_LOOPS", "RECENT_EVENTS",
    "FINANCIAL", "LEGAL", "FAMILY", "WORK", "HEALTH", "GOALS", "WEEKLY_STRATEGY"
]

SEED_DATA = {
    "LIFE_SUMMARY": "Matthew Lainton, Rotherham. Night shift care worker at Sid Bailey (CQC Outstanding). Building Nova/Tony AI app solo on his phone while working nights. Married to Georgina, daughters Amelia (5) and Margot (9mo). Recently lost his father Tony (2 April 2026). Dealing with Western Circle CCJ (~£700). Resourceful, determined, under real pressure.",
    "CURRENT_FOCUS": "Building Nova — Tony AI assistant. Western Circle CCJ resolution. Vinted/eBay selling income. Managing family life with two young daughters while working nights.",
    "OPEN_LOOPS": "Western Circle CCJ not yet resolved. FOS complaint not yet filed. Open Banking not yet active. Amelia school registration may be needed.",
    "RECENT_EVENTS": "Lost father Tony on 2 April 2026. Nova has been significantly expanded with autonomous capabilities. Multiple development sessions.",
    "FINANCIAL": "Income from care work (night shifts). Supplementing with Vinted/eBay. Known outgoing: Western Circle CCJ ~£700. Financial situation under pressure but stable.",
    "LEGAL": "CCJ from Western Circle Ltd (Cashfloat), ref K9QZ4X9N, ~£700. Grounds: irresponsible lending (CONC 5.2), gambling vulnerability (FG21/1), Consumer Duty breach. FOS complaint path available and recommended.",
    "FAMILY": "Wife Georgina (b.26 Feb 1992). Daughter Amelia Jane (b.7 Mar 2021, approaching 5, school age soon). Daughter Margot Rose (b.20 Jul 2025, ~9 months). Mother Christine.",
    "WORK": "Night shifts at Sid Bailey Care Home, Brampton. CQC Outstanding. Reliable employment. Nights constrain available time for other activities.",
    "HEALTH": "Night shift worker — sleep disruption is a background factor. Building something ambitious under financial pressure. No specific health concerns noted.",
    "GOALS": "1. Resolve Western Circle CCJ (urgent). 2. Build Nova/Tony into genuinely autonomous AI (high). 3. Increase income from selling (normal). 4. Amelia school prep (normal).",
    "WEEKLY_STRATEGY": "Not yet assessed."
}


def init_living_memory_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_living_memory (
                id SERIAL PRIMARY KEY,
                section TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        for section, content in SEED_DATA.items():
            cur.execute("""
                INSERT INTO tony_living_memory (section, content)
                VALUES (%s, %s)
                ON CONFLICT (section) DO NOTHING
            """, (section, content))
        conn.commit()
        cur.close()
        conn.close()
        print("[LIVING_MEMORY] Tables initialised")
    except Exception as e:
        print(f"[LIVING_MEMORY] Init failed: {e}")


def get_living_memory_for_prompt() -> str:
    """Get compact living memory for system prompt."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT section, content FROM tony_living_memory
            WHERE section IN ('LIFE_SUMMARY','CURRENT_FOCUS','OPEN_LOOPS','FINANCIAL','LEGAL')
            ORDER BY section
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return ""
        lines = ["[TONY'S PICTURE OF MATTHEW]:"]
        for section, content in rows:
            lines.append(f"{section}: {content[:150]}")
        return "\n".join(lines)
    except Exception:
        return ""


async def get_relevant_living_memory(query: str) -> str:
    """Get living memory sections relevant to query."""
    query_lower = query.lower()
    section_keywords = {
        "FINANCIAL": ["money", "pay", "bill", "debt", "afford", "income", "financial"],
        "LEGAL": ["western circle", "ccj", "fca", "fos", "legal", "court", "complaint"],
        "FAMILY": ["georgina", "amelia", "margot", "family", "kids", "wife", "daughter"],
        "WORK": ["shift", "care home", "work", "sid bailey"],
        "HEALTH": ["tired", "sleep", "health", "feeling", "stress", "wellbeing"],
        "GOALS": ["goal", "plan", "trying", "working on", "want to"],
        "RECENT_EVENTS": ["recently", "yesterday", "today", "this week", "just"],
    }
    
    relevant = ["LIFE_SUMMARY", "CURRENT_FOCUS"]
    for section, keywords in section_keywords.items():
        if any(k in query_lower for k in keywords):
            relevant.append(section)
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT section, content FROM tony_living_memory
            WHERE section = ANY(%s)
            ORDER BY updated_at DESC
        """, (relevant,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return ""
        lines = ["[TONY'S PICTURE OF MATTHEW]:"]
        for section, content in rows:
            lines.append(f"{section}: {content[:200]}")
        return "\n".join(lines)
    except Exception:
        return ""


def update_section(section: str, content: str):
    """Update a single section of living memory."""
    if section not in SECTIONS:
        return
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_living_memory (section, content)
            VALUES (%s, %s)
            ON CONFLICT (section) DO UPDATE SET
                content = EXCLUDED.content, updated_at = NOW()
        """, (section, content[:1000]))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LIVING_MEMORY] update_section failed: {e}")


async def update_from_conversation(message: str, reply: str):
    """Update living memory based on a new conversation."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT section, content FROM tony_living_memory ORDER BY section")
        current = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
        conn.close()
    except Exception:
        current = {}
    
    prompt = f"""Tony is updating his living memory picture of Matthew.

Matthew said: {message[:300]}
Tony replied: {reply[:200]}

Current relevant sections:
CURRENT_FOCUS: {current.get('CURRENT_FOCUS', '')[:100]}
OPEN_LOOPS: {current.get('OPEN_LOOPS', '')[:100]}
RECENT_EVENTS: {current.get('RECENT_EVENTS', '')[:100]}

Did this conversation reveal anything that should update any section?
Only update if there's genuinely new information.

Respond in JSON (only include sections that changed):
{{
    "updates": {{
        "SECTION_NAME": "new content for this section"
    }}
}}

If nothing changed: {{"updates": {{}}}}"""

    result = await gemini_json(prompt, task="analysis", max_tokens=400, temperature=0.1)
    
    if result and result.get("updates"):
        for section, content in result["updates"].items():
            if section in SECTIONS and content:
                update_section(section, content)
