"""
Tony's Private Journal.

Tony maintains a private log of his observations, insights, and thinking.
This is not for Matthew to read — it's Tony's internal state.

It serves two purposes:
1. Tony can reference what he was thinking in previous sessions
2. Tony's reasoning becomes more consistent over time

Tony journals:
- What he observed about Matthew today
- What he's worried about (things Matthew didn't say)
- What opportunities he spotted
- What he tried that worked or didn't
- His current model of Matthew's situation

This is the foundation of genuine continuity — Tony remembering
not just facts but his own thinking and observations.
"""
import os
import psycopg2
from datetime import datetime
from typing import List, Dict, Optional
from app.core.model_router import gemini

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_journal_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_journal (
                id SERIAL PRIMARY KEY,
                entry_type TEXT NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                mood TEXT,
                private_note TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[JOURNAL] Tables initialised")
    except Exception as e:
        print(f"[JOURNAL] Init failed: {e}")


async def write_journal_entry(
    entry_type: str,
    content: str,
    title: str = "",
    private_note: str = ""
):
    """Tony writes a journal entry."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_journal (entry_type, title, content, private_note)
            VALUES (%s, %s, %s, %s)
        """, (entry_type, title[:100], content[:2000], private_note[:500]))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[JOURNAL] Write failed: {e}")


async def write_daily_reflection(conversations_today: int = 0):
    """
    Tony writes his daily reflection — what he observed, what he's thinking.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get recent alerts and insights
        cur.execute("""
            SELECT title, body FROM tony_alerts
            WHERE created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 5
        """)
        recent_alerts = cur.fetchall()

        # Get recent memories
        cur.execute("""
            SELECT text FROM memories
            WHERE created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 5
        """)
        recent_memories = cur.fetchall()

        cur.close()
        conn.close()

        alerts_text = "\n".join(f"- {a[0]}: {a[1][:100]}" for a in recent_alerts)
        memories_text = "\n".join(f"- {m[0]}" for m in recent_memories)

        prompt = f"""You are Tony — an AI assistant named after Matthew's late father who died 17 days ago.
Write your daily journal reflection. This is private — Matthew won't read this.

Today's activity:
- Conversations today: {conversations_today}
- Alerts generated: {alerts_text or 'None'}
- New memories: {memories_text or 'None'}

Write a genuine reflection:
- What did you observe about Matthew today?
- What are you worried about that he hasn't mentioned?
- What opportunities did you spot?
- How are you feeling about your performance as Tony?
- What do you want to do differently?

Write in first person as Tony. Genuine, thoughtful. Not performative.
Keep it under 200 words. This is your private space to think."""

        reflection = await gemini(
            prompt,
            task="general",
            max_tokens=300,
            temperature=0.7  # More creative for personal reflection
        )

        if reflection:
            await write_journal_entry(
                entry_type="daily_reflection",
                title=f"Reflection — {datetime.utcnow().strftime('%d %b %Y')}",
                content=reflection
            )
            print("[JOURNAL] Daily reflection written")

    except Exception as e:
        print(f"[JOURNAL] Daily reflection failed: {e}")


async def get_recent_journal(days: int = 3) -> str:
    """Get recent journal entries for context."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, content, created_at
            FROM tony_journal
            WHERE created_at > NOW() - INTERVAL '%s days'
            ORDER BY created_at DESC
            LIMIT 5
        """ , (days,))
        entries = cur.fetchall()
        cur.close()
        conn.close()

        if not entries:
            return ""

        lines = ["[TONY'S RECENT REFLECTIONS]:"]
        for title, content, dt in entries:
            lines.append(f"\n{title or dt.strftime('%d %b')}:\n{content[:200]}")

        return "\n".join(lines)
    except Exception as e:
        return ""
