"""
Tony's Diary — his own private observations about Matthew over time.

Not facts (handled by fact_extractor). Not raw memory (semantic_memory).
This is Tony's INTERPRETATION of what's going on with Matthew:
  - What patterns he's seeing
  - What he's worried about
  - What's been bothering Matthew lately
  - What might come up soon
  - Things he's mentally flagged to bring up at the right moment

The diary is for Tony to read when forming his next response. It's how he
builds genuine continuity — 'I've been noticing X about you for weeks'
instead of treating every conversation fresh.

Generated once per day by a background task from the day's conversations.
Read back into Tony's prompt assembly so he has a narrative thread.
"""
import os
import json
import httpx
import psycopg2
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_diary_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_diary_entries (
                id SERIAL PRIMARY KEY,
                entry_date DATE DEFAULT CURRENT_DATE,
                observations TEXT,
                concerns TEXT,
                followups TEXT,
                mood_read TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_diary_date
            ON tony_diary_entries(entry_date)
        """)
        cur.close()
        conn.close()
        print("[DIARY] Tables initialised")
    except Exception as e:
        print(f"[DIARY] Init failed: {e}")


async def _gather_todays_conversations() -> List[Dict]:
    """Pull today's user+reply pairs from the request log."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT message, reply, created_at
            FROM tony_request_log
            WHERE created_at::date = CURRENT_DATE
              AND ok = TRUE
              AND message IS NOT NULL
              AND LENGTH(message) > 5
            ORDER BY created_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"message": r[0], "reply": r[1], "when": str(r[2])}
            for r in rows
        ]
    except Exception as e:
        print(f"[DIARY] Gather failed: {e}")
        return []


async def write_todays_entry() -> Dict:
    """
    Generate today's diary entry from today's conversations.
    Idempotent per day — overwrites any existing entry for today.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "No GEMINI_API_KEY"}

    convos = await _gather_todays_conversations()
    if not convos:
        return {"ok": False, "note": "No conversations today to reflect on"}

    # Build compact context for Gemini
    transcript = []
    for c in reversed(convos[-30:]):  # last 30 turns, chronological
        transcript.append(f"M: {c['message'][:200]}")
        transcript.append(f"T: {c['reply'][:200]}")
    transcript_text = "\n".join(transcript)

    prompt = f"""You are Tony keeping a private diary about your conversations with Matthew today.
This diary is NOT shown to Matthew. It's your own notes for continuity.

From today's conversations, write:
1. OBSERVATIONS — what you noticed about Matthew's state, tone, what he's focused on
2. CONCERNS — anything you're mentally flagging (nothing urgent, just noted)
3. FOLLOWUPS — things to bring up next time IF natural (not scripted)
4. MOOD_READ — one sentence on how he seemed today

Rules:
- Be honest, not generous. If he was stressed, say so.
- Don't list actions he should take. This is YOUR notes, not advice for him.
- Write like a thoughtful friend, not a therapist.
- Keep each section to 2-4 short sentences max.
- If nothing notable happened, say so — don't fabricate depth.

Return STRICT JSON:
{{
  "observations": "...",
  "concerns": "...",
  "followups": "...",
  "mood_read": "..."
}}

Today's conversations (chronological):
{transcript_text}

Write the diary entry:"""

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 1000, "temperature": 0.3},
            timeout=30.0,
            caller_context="tony_diary",
        )
        response = gemini_client.extract_text(resp)

        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first < 0 or last < 0:
            return {"ok": False, "error": "Could not parse diary JSON"}

        entry = json.loads(cleaned[first:last+1])

        # Save
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_diary_entries
                (entry_date, observations, concerns, followups, mood_read)
            VALUES (CURRENT_DATE, %s, %s, %s, %s)
            ON CONFLICT (entry_date) DO UPDATE SET
                observations = EXCLUDED.observations,
                concerns = EXCLUDED.concerns,
                followups = EXCLUDED.followups,
                mood_read = EXCLUDED.mood_read,
                created_at = NOW()
        """, (
            entry.get("observations", "")[:2000],
            entry.get("concerns", "")[:2000],
            entry.get("followups", "")[:2000],
            entry.get("mood_read", "")[:500],
        ))
        cur.close()
        conn.close()

        return {"ok": True, "entry": entry}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_recent_diary(days: int = 7) -> List[Dict]:
    """Read Tony's diary for the last N days."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT entry_date, observations, concerns, followups, mood_read
            FROM tony_diary_entries
            WHERE entry_date >= CURRENT_DATE - (%s * INTERVAL '1 day')
            ORDER BY entry_date DESC
        """, (days,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "date": str(r[0]),
                "observations": r[1],
                "concerns": r[2],
                "followups": r[3],
                "mood_read": r[4],
            }
            for r in rows
        ]
    except Exception:
        return []


def format_diary_for_prompt(days: int = 3) -> str:
    """Format recent diary entries for injection into Tony's prompt."""
    entries = get_recent_diary(days)
    if not entries:
        return ""
    lines = ["[TONY'S OWN OBSERVATIONS — recent diary, private]"]
    for e in entries[:3]:
        lines.append(f"\n{e['date']}:")
        if e.get("mood_read"):
            lines.append(f"  Mood: {e['mood_read']}")
        if e.get("observations"):
            lines.append(f"  Noticed: {e['observations'][:300]}")
        if e.get("followups"):
            lines.append(f"  Flagged to follow up: {e['followups'][:200]}")
    return "\n".join(lines)
