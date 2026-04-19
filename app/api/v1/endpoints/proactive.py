"""
Tony's Proactive endpoint - alerts, briefings, notifications.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
import psycopg2
import os

router = APIRouter()

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


@router.get("/proactive/briefing")
async def get_briefing(_=Depends(verify_token)):
    """
    Tony's startup briefing - fast, substantive, from live state.
    Pulls from actual data rather than asking an LLM to guess.
    """
    briefing_parts = []
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Unread high-priority alerts
        cur.execute("""
            SELECT title, body FROM tony_alerts
            WHERE read = FALSE AND priority IN ('urgent', 'high')
            AND created_at > NOW() - INTERVAL '48 hours'
            ORDER BY created_at DESC LIMIT 3
        """)
        alerts = cur.fetchall()
        if alerts:
            briefing_parts.append("**Alerts needing your attention:**")
            for title, body in alerts:
                briefing_parts.append(f"• {title}: {body[:100]}")
        
        # Pending email approvals
        cur.execute("SELECT COUNT(*) FROM tony_email_queue WHERE approval_status = 'pending'")
        pending = cur.fetchone()[0]
        if pending > 0:
            briefing_parts.append(f"**{pending} email(s) waiting for your approval** — tap + then 'Check pending emails'")
        
        # Active urgent/high goals
        cur.execute("""
            SELECT title, priority FROM tony_goals
            WHERE status = 'active' AND priority IN ('urgent', 'high')
            ORDER BY CASE priority WHEN 'urgent' THEN 1 ELSE 2 END LIMIT 2
        """)
        goals = cur.fetchall()
        if goals:
            briefing_parts.append("**Active priorities:**")
            for title, pri in goals:
                briefing_parts.append(f"• {title} ({pri})")
        
        # Family dates coming up
        from datetime import date, timedelta
        today = date.today()
        family_dates = [
            (date(today.year, 2, 26), "Georgina's birthday"),
            (date(today.year, 3, 7), "Amelia's birthday"),
            (date(today.year, 7, 20), "Margot's birthday"),
            (date(today.year, 6, 4), "Dad's birthday"),
            (date(today.year, 4, 2), "Anniversary of Dad's passing"),
        ]
        for event_date, event_name in family_dates:
            if event_date < today:
                event_date = event_date.replace(year=today.year + 1)
            days_until = (event_date - today).days
            if 0 <= days_until <= 14:
                briefing_parts.append(f"**{event_name}** in {days_until} days ({event_date.strftime('%d %b')})")
        
        # Weekly strategy if exists
        cur.execute("SELECT content FROM tony_living_memory WHERE section = 'WEEKLY_STRATEGY'")
        row = cur.fetchone()
        if row and row[0] and row[0] != "Not yet assessed.":
            briefing_parts.append(f"**This week:** {row[0][:150]}")
        
        # What Tony did in the last 6 hours
        cur.execute("""
            SELECT COUNT(*) FROM tony_build_log
            WHERE success = TRUE AND created_at > NOW() - INTERVAL '6 hours'
        """)
        builds = cur.fetchone()[0]
        if builds > 0:
            briefing_parts.append(f"Tony completed {builds} autonomous tasks while you were away.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        briefing_parts.append(f"Tony ready. (System note: {str(e)[:50]})")
    
    if not briefing_parts:
        briefing_parts.append("All clear — no urgent items. What do you need?")
    
    return {
        "ok": True,
        "briefing": "\n\n".join(briefing_parts),
        "parts": len(briefing_parts)
    }


@router.get("/proactive/alerts")
async def get_alerts(_=Depends(verify_token)):
    """Get all unread alerts."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, alert_type, title, body, priority, source, created_at
            FROM tony_alerts
            WHERE read = FALSE
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, created_at DESC
            LIMIT 20
        """)
        alerts = [
            {"id": r[0], "type": r[1], "title": r[2], "body": r[3],
             "priority": r[4], "source": r[5], "created": str(r[6])}
            for r in cur.fetchall()
        ]
        cur.close()
        conn.close()
        return {"ok": True, "alerts": alerts, "count": len(alerts)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/proactive/mark-read/{alert_id}")
async def mark_read(alert_id: int, _=Depends(verify_token)):
    """Mark an alert as read."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE tony_alerts SET read = TRUE WHERE id = %s", (alert_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def create_alert(
    alert_type: str, title: str, body: str,
    priority: str = "normal", source: str = "system"
):
    """Create a new alert."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_alerts (
                id SERIAL PRIMARY KEY,
                alert_type TEXT,
                title TEXT,
                body TEXT,
                priority TEXT DEFAULT 'normal',
                source TEXT,
                read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            INSERT INTO tony_alerts (alert_type, title, body, priority, source)
            VALUES (%s, %s, %s, %s, %s)
        """, (alert_type, title[:200], body[:500], priority, source))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[PROACTIVE] create_alert failed: {e}")
