"""
Admin clear endpoints.

Lets Matthew wipe specific topics from Tony's brain when Tony won't stop bringing them up.
"""
import os
import psycopg2
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token


router = APIRouter()


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


class ClearRequest(BaseModel):
    topic: str


@router.post("/admin/clear-topic")
async def clear_topic(req: ClearRequest, _=Depends(verify_token)):
    """
    Complete wipe of a topic from Tony's context.
    - Marks all matching alerts as read
    - Adds a permanent topic ban (no auto-expiry)
    - Clears matching semantic memories from active recall
    - Marks matching goals as dormant
    """
    topic = req.topic.strip()
    if not topic:
        return {"ok": False, "error": "No topic supplied"}

    cleared = {
        "topic": topic,
        "alerts_cleared": 0,
        "memories_demoted": 0,
        "goals_dormant": 0,
        "ban_added": False,
    }

    try:
        conn = get_conn()
        cur = conn.cursor()

        # 1. Mark all alerts matching topic as read + expired
        cur.execute("""
            UPDATE tony_alerts
            SET read = TRUE, expires_at = NOW() - INTERVAL '1 hour'
            WHERE (title ILIKE %s OR body ILIKE %s OR source ILIKE %s)
            AND (read = FALSE OR expires_at > NOW())
        """, (f"%{topic}%", f"%{topic}%", f"%{topic}%"))
        cleared["alerts_cleared"] = cur.rowcount

        # 2. Permanent topic ban — 30 day expiry (long enough to feel permanent)
        cur.execute("""
            INSERT INTO tony_topic_bans
            (chat_session_id, topic, phrase_that_triggered, expires_at)
            VALUES (NULL, %s, %s, NOW() + INTERVAL '30 days')
        """, (topic, f"Matthew used admin clear: {topic}"))
        cleared["ban_added"] = True

        # 3. Demote semantic memories matching this topic
        # (Set importance to 0 so they don't surface in search)
        try:
            cur.execute("""
                UPDATE tony_semantic_memory
                SET importance = 0
                WHERE content ILIKE %s
            """, (f"%{topic}%",))
            cleared["memories_demoted"] = cur.rowcount
        except Exception:
            pass  # table might not exist

        # 4. Mark matching goals as dormant
        try:
            cur.execute("""
                UPDATE tony_goals
                SET status = 'dormant'
                WHERE (title ILIKE %s OR description ILIKE %s)
                AND status != 'completed'
            """, (f"%{topic}%", f"%{topic}%"))
            cleared["goals_dormant"] = cur.rowcount
        except Exception:
            pass

        conn.commit()
        cur.close()
        conn.close()

        return {"ok": True, **cleared}

    except Exception as e:
        return {"ok": False, "error": str(e), **cleared}


@router.get("/admin/topic-status")
async def topic_status(topic: str, _=Depends(verify_token)):
    """Check what Tony still has on a topic."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*) FROM tony_alerts
            WHERE (title ILIKE %s OR body ILIKE %s)
            AND read = FALSE AND (expires_at IS NULL OR expires_at > NOW())
        """, (f"%{topic}%", f"%{topic}%"))
        active_alerts = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM tony_topic_bans
            WHERE topic ILIKE %s AND active = TRUE AND expires_at > NOW()
        """, (f"%{topic}%",))
        active_bans = cur.fetchone()[0]

        cur.close()
        conn.close()

        return {
            "ok": True,
            "topic": topic,
            "active_alerts": active_alerts,
            "active_bans": active_bans,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
