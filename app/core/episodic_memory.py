"""
Tony's Episodic Memory.

The difference between knowing facts and remembering experiences.

Factual memory: "Matthew works at Sid Bailey Care Home"
Episodic memory: "18 Apr 2026 — Matthew asked about Azure TTS. We set it up together.
                  He was frustrated with Chrome corrupting file downloads."

Episodic memory lets Tony:
- Know what was tried and what worked
- Avoid repeating the same mistakes
- Reference shared history naturally
- Build a genuine relationship over time

Stored in tony_episodes table. Injected into system prompt as recent context.
Tony can also search episodes when relevant.
"""
import os
import re
import json
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_episodic_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_episodes (
                id SERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                summary TEXT NOT NULL,
                outcome TEXT,
                emotion TEXT,
                tags TEXT[],
                significant BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[EPISODIC] Tables initialised")
    except Exception as e:
        print(f"[EPISODIC] Init failed: {e}")


def save_episode(summary: str, outcome: str = None, emotion: str = None,
                 tags: List[str] = None, significant: bool = False):
    """Save a single episode to DB."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        today = datetime.utcnow().strftime("%d %b %Y")
        cur.execute("""
            INSERT INTO tony_episodes (date, summary, outcome, emotion, tags, significant)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (today, summary[:800], outcome, emotion, tags or [], significant))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[EPISODIC] Save failed: {e}")


def get_recent_episodes(days: int = 7, limit: int = 10) -> List[Dict]:
    """Get recent episodes for system prompt injection."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT date, summary, outcome, emotion, significant
            FROM tony_episodes
            WHERE created_at > NOW() - INTERVAL '%s days'
            ORDER BY created_at DESC
            LIMIT %s
        """, (days, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "date": r[0], "summary": r[1], "outcome": r[2],
                "emotion": r[3], "significant": r[4]
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[EPISODIC] Fetch failed: {e}")
        return []


def get_significant_episodes(limit: int = 5) -> List[Dict]:
    """Get the most significant episodes Tony should always remember."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT date, summary, outcome
            FROM tony_episodes
            WHERE significant = TRUE
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"date": r[0], "summary": r[1], "outcome": r[2]} for r in rows]
    except Exception as e:
        print(f"[EPISODIC] Significant fetch failed: {e}")
        return []


def search_episodes(query: str, limit: int = 5) -> List[Dict]:
    """Search episodes by keyword."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT date, summary, outcome, emotion
            FROM tony_episodes
            WHERE summary ILIKE %s OR outcome ILIKE %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (f"%{query}%", f"%{query}%", limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"date": r[0], "summary": r[1], "outcome": r[2], "emotion": r[3]} for r in rows]
    except Exception as e:
        print(f"[EPISODIC] Search failed: {e}")
        return []


def format_episodic_block() -> str:
    """Format recent episodes for system prompt injection."""
    try:
        recent = get_recent_episodes(days=3, limit=5)
        significant = get_significant_episodes(limit=3)

        if not recent and not significant:
            return ""

        lines = ["[RECENT EXPERIENCES]"]

        if significant:
            for ep in significant:
                line = f"• {ep['date']}: {ep['summary']}"
                if ep.get('outcome'):
                    line += f" → {ep['outcome']}"
                lines.append(line)

        if recent:
            seen = {ep['summary'] for ep in significant}
            for ep in recent:
                if ep['summary'] not in seen:
                    line = f"• {ep['date']}: {ep['summary']}"
                    if ep.get('outcome'):
                        line += f" → {ep['outcome']}"
                    lines.append(line)

        return "\n".join(lines[:8])  # Cap at 8 lines to keep prompt lean
    except Exception as e:
        print(f"[EPISODIC] Format failed: {e}")
        return ""


async def extract_episode_from_conversation(message: str, reply: str) -> Optional[Dict]:
    """
    After each conversation, Tony decides if it's worth remembering as an experience.
    Not every message becomes an episode — only meaningful ones.
    """
    if not GEMINI_API_KEY:
        return None

    # Quick filter — short exchanges rarely need episodic memory
    if len(message) < 30 and len(reply) < 100:
        return None

    prompt = f"""You are Tony's episodic memory system. Decide if this conversation is worth remembering as an experience.

Matthew said: {message[:400]}
Tony replied: {reply[:400]}

Is this worth remembering? Consider:
- Was something built, fixed, or deployed?
- Was a decision made?
- Was there an emotional moment?
- Was something tried that worked or failed?
- Was there something new learned?

If YES, extract the episode. If NO (just a casual question/answer), return null.

Respond in JSON only:
{{
    "worth_remembering": true/false,
    "summary": "one sentence describing what happened",
    "outcome": "what the result was (optional)",
    "emotion": "tone/emotion if notable (optional)",
    "tags": ["tag1", "tag2"],
    "significant": true/false
}}

significant=true only for major milestones like features built, important decisions, or emotionally significant moments."""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 512, "temperature": 0.2}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r'```json|```', '', text).strip()
            data = json.loads(text)

            if not data.get("worth_remembering"):
                return None

            return {
                "summary": data.get("summary", ""),
                "outcome": data.get("outcome"),
                "emotion": data.get("emotion"),
                "tags": data.get("tags", []),
                "significant": data.get("significant", False)
            }
    except Exception as e:
        print(f"[EPISODIC] Extraction failed: {e}")
        return None


async def process_conversation_for_episode(message: str, reply: str):
    """Called after every conversation. Extracts and saves episode if worthy."""
    episode = await extract_episode_from_conversation(message, reply)
    if episode:
        save_episode(
            summary=episode["summary"],
            outcome=episode.get("outcome"),
            emotion=episode.get("emotion"),
            tags=episode.get("tags", []),
            significant=episode.get("significant", False)
        )
        print(f"[EPISODIC] Saved: {episode['summary'][:80]}")
