"""
Tony's Goal Tracking System.

Tony holds Matthew's goals across sessions.
He works on them autonomously, tracks progress, identifies blockers,
and reports back without being asked.

A goal isn't just a note — it's something Tony actively pursues.
"""
import os
import json
import httpx
import psycopg2
from datetime import datetime
from typing import List, Dict, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_goals_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_goals (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT DEFAULT 'general',
                status TEXT DEFAULT 'active',
                priority TEXT DEFAULT 'normal',
                progress_notes TEXT,
                next_action TEXT,
                blockers TEXT,
                target_date TEXT,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()

        # Seed with Matthew's known goals
        known_goals = [
            (
                "Remove Western Circle CCJ",
                "CCJ from Western Circle / Cashfloat. Amount ~£700. Case ref K9QZ4X9N. Grounds: vulnerability due to gambling addiction and family dementia. 22 emails ingested and analysed.",
                "legal", "active", "urgent",
                "22 emails ingested into RAG. FCA complaint grounds identified.",
                "Compile full case from emails, draft formal FCA complaint letter, send to Financial Conduct Authority",
                "Case emails ingested but RAG search needs verifying",
                None
            ),
            (
                "Build Tony into the most capable personal AI",
                "Nova app - Tony as autonomous AI agent with world model, multi-brain council, self-improvement loop",
                "technology", "active", "high",
                "Core built: chat, memory, Gmail, vision, RAG, agent, builder, world model, calendar, proactive alerts",
                "Verify RAG working, set up cron job, test end to end autonomy",
                "RAG vector search needs case rebuild after table reset",
                None
            ),
            (
                "Financial stability for family",
                "Ensure Georgina, Amelia and Margot are secure. Resolve debts. Build income streams.",
                "financial", "active", "high",
                "Western Circle CCJ is primary financial threat being addressed",
                "Resolve CCJ first, then look at income opportunities",
                None, None
            ),
            (
                "Vinted/eBay resale business",
                "Use Tony to photograph items, research values, create listings, sell on Vinted and eBay",
                "business", "pending", "normal",
                "Vision system built. Product photography and listing drafting possible.",
                "Build eBay API integration, then Vinted browser automation",
                "Waiting for core Tony to stabilise first",
                None
            )
        ]

        # Add unique constraint on title if not exists
        try:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS tony_goals_title_idx ON tony_goals(title)")
            conn.commit()
        except Exception:
            conn.rollback()

        # Remove duplicates keeping lowest id
        try:
            cur.execute("""
                DELETE FROM tony_goals a USING tony_goals b
                WHERE a.id > b.id AND a.title = b.title
            """)
            conn.commit()
        except Exception:
            conn.rollback()  # logged above

        for title, desc, cat, status, priority, progress, next_action, blockers, target in known_goals:
            cur.execute("""
                INSERT INTO tony_goals
                (title, description, category, status, priority, progress_notes, next_action, blockers, target_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (title) DO NOTHING
            """, (title, desc, cat, status, priority, progress, next_action, blockers, target))

        conn.commit()
        cur.close()
        conn.close()
        print("[GOALS] Initialised")
    except Exception as e:
        print(f"[GOALS] Init failed: {e}")


def get_active_goals() -> List[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, description, category, status, priority,
                   progress_notes, next_action, blockers, target_date, updated_at
            FROM tony_goals
            WHERE status IN ('active', 'pending')
            ORDER BY
                CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
                updated_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "title": r[1], "description": r[2],
                "category": r[3], "status": r[4], "priority": r[5],
                "progress": r[6], "next_action": r[7], "blockers": r[8],
                "target": r[9], "updated": str(r[10])
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[GOALS] Fetch failed: {e}")
        return []


def update_goal_progress(goal_id: int, progress: str = None,
                          next_action: str = None, blockers: str = None,
                          status: str = None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        updates = ["updated_at = NOW()"]
        values = []
        if progress:
            updates.append("progress_notes = %s")
            values.append(progress)
        if next_action:
            updates.append("next_action = %s")
            values.append(next_action)
        if blockers is not None:
            updates.append("blockers = %s")
            values.append(blockers)
        if status:
            updates.append("status = %s")
            values.append(status)
            if status == "completed":
                updates.append("completed_at = NOW()")
        values.append(goal_id)
        cur.execute(f"UPDATE tony_goals SET {', '.join(updates)} WHERE id = %s", values)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[GOALS] Update failed: {e}")


def add_goal(title: str, description: str, category: str = "general",
             priority: str = "normal", next_action: str = None) -> int:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_goals (title, description, category, priority, next_action)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (title, description, category, priority, next_action))
        goal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return goal_id
    except Exception as e:
        print(f"[GOALS] Add failed: {e}")
        return -1


def get_goals_summary() -> str:
    """Summary for Tony's system prompt."""
    goals = get_active_goals()
    if not goals:
        return ""
    lines = [f"[TONY'S ACTIVE GOALS — {len(goals)} goals Tony is working on]\n"]
    for g in goals:
        priority_marker = "🔴" if g["priority"] == "urgent" else "🟡" if g["priority"] == "high" else "🟢"
        lines.append(f"{priority_marker} {g['title']} [{g['category']}]")
        if g["next_action"]:
            lines.append(f"   Next: {g['next_action']}")
        if g["blockers"]:
            lines.append(f"   Blocked by: {g['blockers']}")
    return "\n".join(lines)


async def tony_work_on_goals():
    """
    Tony autonomously works on his active goals.
    For each goal he assesses progress and identifies next actions.
    """
    goals = get_active_goals()
    worked_on = []

    for goal in goals[:3]:  # Work on top 3 priority goals
        try:
            prompt = f"""You are Tony working autonomously on one of Matthew's goals.

GOAL: {goal['title']}
DESCRIPTION: {goal['description']}
CURRENT PROGRESS: {goal['progress'] or 'Not started'}
CURRENT NEXT ACTION: {goal['next_action'] or 'Not defined'}
BLOCKERS: {goal['blockers'] or 'None'}

What can Tony do RIGHT NOW to advance this goal?
Consider: research, drafting documents, searching emails, building capabilities, creating alerts.

Respond in JSON:
{{
    "can_advance": true/false,
    "action_taken": "what Tony did or will do",
    "new_progress_notes": "updated progress",
    "new_next_action": "what should happen next",
    "alert_needed": "message for Matthew if he needs to know something" or null
}}"""

            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {"maxOutputTokens": 512, "temperature": 0.3}
                    }
                )
                r.raise_for_status()
                response = r.json()["candidates"][0]["content"]["parts"][0]["text"]

                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())

                    update_goal_progress(
                        goal["id"],
                        progress=data.get("new_progress_notes"),
                        next_action=data.get("new_next_action")
                    )

                    if data.get("alert_needed"):
                        from app.core.proactive import create_alert
                        create_alert(
                            alert_type="goal_update",
                            title=f"Goal update: {goal['title']}",
                            body=data["alert_needed"],
                            priority="normal",
                            source=f"goal_{goal['id']}"
                        )

                    worked_on.append({
                        "goal": goal["title"],
                        "advanced": data.get("can_advance", False),
                        "action": data.get("action_taken", "")
                    })
        except Exception as e:
            print(f"[GOALS] Work on '{goal['title']}' failed: {e}")

    return worked_on
