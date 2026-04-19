"""
Tony detects goals from conversation and creates them automatically.

When Matthew says "I want to...", "I need to...", "I'm trying to...",
Tony detects it, creates a structured goal, and starts working on it.

No more manually adding goals. Tony hears what Matthew wants and tracks it.
"""
import os
import re
import psycopg2
from datetime import datetime
from typing import Optional, Dict
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


GOAL_TRIGGERS = [
    "i want to", "i need to", "i'm trying to", "i'm working on",
    "my goal is", "i'd like to", "i'm planning to", "i hope to",
    "we need to", "trying to figure out", "want to sort out",
    "need to sort", "need to fix", "want to build", "want to get"
]


def might_contain_goal(message: str) -> bool:
    """Quick check if message might contain a goal statement."""
    msg_lower = message.lower()
    return any(trigger in msg_lower for trigger in GOAL_TRIGGERS)


async def detect_and_create_goal(message: str, reply: str) -> Optional[Dict]:
    """
    Detect if a goal was expressed and create it automatically.
    """
    if not might_contain_goal(message):
        return None
    
    prompt = f"""Tony is reading a conversation to detect if Matthew expressed a goal.

Matthew said: {message[:400]}
Tony replied: {reply[:200]}

Did Matthew express a clear goal or intention he wants to achieve?

Rules:
- Only detect REAL goals, not casual mentions
- Must be something Matthew actually wants to accomplish
- Must be achievable (not "I want world peace")
- Short throwaway statements are NOT goals

If a real goal was expressed, extract it.
If not, return null.

Respond in JSON:
{{
    "goal_detected": true/false,
    "title": "short goal title (or null)",
    "description": "what Matthew wants to achieve (or null)",
    "priority": "urgent/high/normal/low",
    "category": "legal/financial/work/personal/nova/selling/family"
}}

If no goal: {{"goal_detected": false}}"""

    result = await gemini_json(prompt, task="analysis", max_tokens=256, temperature=0.1)
    if not result or not result.get("goal_detected"):
        return None
    
    title = result.get("title", "")
    if not title or len(title) < 5:
        return None
    
    # Check if goal already exists
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM tony_goals WHERE LOWER(title) LIKE %s LIMIT 1",
            (f"%{title[:20].lower()}%",)
        )
        existing = cur.fetchone()
        
        if not existing:
            cur.execute("""
                INSERT INTO tony_goals (title, description, priority, status, created_at)
                VALUES (%s, %s, %s, 'active', NOW())
            """, (title[:200], result.get("description", "")[:500], result.get("priority", "normal")))
            conn.commit()
            print(f"[GOAL_DETECTOR] New goal created: {title}")
        
        cur.close()
        conn.close()
        return result if not existing else None
        
    except Exception as e:
        print(f"[GOAL_DETECTOR] Failed: {e}")
        return None
