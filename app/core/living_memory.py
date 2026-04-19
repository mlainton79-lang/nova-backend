"""
Tony's Living Memory.

This is the most important upgrade to Tony's intelligence.

Instead of storing disconnected facts, Tony maintains a continuously
updated, structured document about Matthew's life. After every
conversation, this document is reviewed and updated.

It's the difference between Tony having a pile of notes
and Tony having a genuinely current understanding of your life.

Structure:
- LIFE_SUMMARY: Who Matthew is right now, in one paragraph
- CURRENT_FOCUS: What Matthew is working on / thinking about most
- RELATIONSHIPS: Key people, current status
- FINANCIAL: Current financial picture
- LEGAL: Active legal matters
- WORK: Work situation
- HEALTH: Physical and mental state (from conversations)
- GOALS: Short and long term
- RECENT_EVENTS: Last 2 weeks of significant events
- OPEN_LOOPS: Things mentioned but not resolved
- TONY_NOTES: Things Tony has noticed that Matthew hasn't mentioned
"""
import os
import json
import psycopg2
from datetime import datetime
from typing import Optional, Dict
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_living_memory_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_living_memory (
                id SERIAL PRIMARY KEY,
                section TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW(),
                update_count INTEGER DEFAULT 0
            )
        """)

        # Seed with what we know about Matthew
        sections = {
            "LIFE_SUMMARY": "Matthew Lainton, 40s, lives in Rotherham with wife Georgina and daughters Amelia (4) and Margot (9 months). Works night shifts at Sid Bailey Care Home (CQC Outstanding). Building Nova AI app late nights on his phone. Father Tony Lainton passed away 2 April 2026 — 17 days ago. Originally from Stafford.",
            "CURRENT_FOCUS": "Building Nova/Tony AI system. Managing CCJ from Western Circle (Cashfloat). Getting Tony's capabilities proven and working.",
            "RELATIONSHIPS": "Wife: Georgina Rose Lainton (b. 26 Feb 1992). Daughters: Amelia Jane (b. 7 Mar 2021), Margot Rose (b. 20 Jul 2025). Mother: Christine. Late father: Tony Lainton (b. 4 Jun 1945, d. 2 Apr 2026).",
            "FINANCIAL": "Has CCJ from Western Circle Ltd (Cashfloat) for ~£700, reference K9QZ4X9N. Working on disputing via FCA/FOS. Exact income/expenses unknown.",
            "LEGAL": "Active CCJ: Western Circle Ltd (Cashfloat), ref K9QZ4X9N, ~£700. Grounds: irresponsible lending, vulnerability (gambling addiction at time), CONC 5.2 breach. FOS complaint route available.",
            "WORK": "Night shifts at Sid Bailey Care Home, Brampton, Rotherham. CQC Outstanding rating. Builds Nova after midnight when shifts allow.",
            "HEALTH": "No specific health information shared yet.",
            "GOALS": "1. Make Tony genuinely capable and autonomous. 2. Resolve Western Circle CCJ. 3. Build financial stability. 4. Build Nova into something significant.",
            "RECENT_EVENTS": "Built out Nova significantly — calendar access confirmed (Samsung + Google), WhatsApp via Twilio activated, voice working with ElevenLabs. All 4 Gmail accounts connected with calendar scope.",
            "OPEN_LOOPS": "Western Circle case needs FCA/FOS complaint filed. Twilio auth token shared publicly — needs regenerating.",
            "TONY_NOTES": "Matthew builds late at night — responses should be sharp when he's tired. He values honesty above all. He gets frustrated when Tony claims something works that doesn't. The grief from his father's recent death (17 days ago) is present but not discussed."
        }

        for section, content in sections.items():
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


def get_living_memory() -> Dict[str, str]:
    """Get the full living memory document."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT section, content FROM tony_living_memory ORDER BY section")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        print(f"[LIVING_MEMORY] Get failed: {e}")
        return {}


def get_living_memory_for_prompt() -> str:
    """Format living memory for system prompt injection."""
    memory = get_living_memory()
    if not memory:
        return ""

    priority_sections = [
        "LIFE_SUMMARY", "CURRENT_FOCUS", "FINANCIAL",
        "LEGAL", "OPEN_LOOPS", "RECENT_EVENTS", "TONY_NOTES"
    ]

    lines = ["[TONY'S LIVING PICTURE OF MATTHEW]:"]
    for section in priority_sections:
        if section in memory and memory[section]:
            lines.append(f"\n{section}: {memory[section]}")

    return "\n".join(lines)


def update_section(section: str, content: str):
    """Update a specific section of living memory."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_living_memory (section, content, updated_at, update_count)
            VALUES (%s, %s, NOW(), 1)
            ON CONFLICT (section) DO UPDATE SET
                content = EXCLUDED.content,
                updated_at = NOW(),
                update_count = tony_living_memory.update_count + 1
        """, (section, content[:2000]))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LIVING_MEMORY] Update failed: {e}")


async def update_from_conversation(message: str, reply: str):
    """
    After every conversation, Tony reviews and updates his living picture.
    Uses Gemini Pro for quality of understanding.
    """
    if len(message) < 10:
        return

    current = get_living_memory()
    current_summary = "\n".join(f"{k}: {v[:200]}" for k, v in current.items())

    prompt = f"""You are Tony's living memory system. A conversation just happened with Matthew.

Current picture of Matthew:
{current_summary}

New conversation:
Matthew: {message[:500]}
Tony replied: {reply[:300]}

Review this conversation and identify any updates needed to Tony's picture of Matthew.
Only update sections where something genuinely new or changed was revealed.

Respond in JSON:
{{
    "updates": {{
        "SECTION_NAME": "updated content for this section"
    }},
    "new_open_loop": "anything mentioned but unresolved (or null)",
    "tony_observation": "something Tony noticed that Matthew didn't explicitly say (or null)"
}}

Sections available: LIFE_SUMMARY, CURRENT_FOCUS, RELATIONSHIPS, FINANCIAL, LEGAL, WORK, HEALTH, GOALS, RECENT_EVENTS, OPEN_LOOPS, TONY_NOTES

If nothing meaningful to update: {{"updates": {{}}}}"""

    result = await gemini_json(prompt, task="analysis", max_tokens=1024)
    if not result:
        return

    updates = result.get("updates", {})
    for section, content in updates.items():
        if section and content:
            update_section(section, content)

    if result.get("new_open_loop"):
        existing = current.get("OPEN_LOOPS", "")
        update_section("OPEN_LOOPS", f"{existing}. {result['new_open_loop']}")

    if result.get("tony_observation"):
        existing = current.get("TONY_NOTES", "")
        update_section("TONY_NOTES", f"{existing}. {result['tony_observation']}")

    if updates:
        print(f"[LIVING_MEMORY] Updated {len(updates)} sections")
