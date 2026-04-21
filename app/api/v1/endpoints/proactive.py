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
    Tony's startup briefing. Tries intelligent LLM-synthesised version first;
    falls back to fast DB-only bullets if that fails for any reason.
    """
    # Try the intelligent briefing first — the Android app calls this endpoint
    # and benefits from the richer synthesis automatically.
    try:
        from app.core.intelligent_briefing import get_intelligent_briefing
        result = await get_intelligent_briefing()
        if result.get("ok") and result.get("briefing"):
            text = result["briefing"].strip()
            # Only use smart result if it's not empty / not just fallback
            if text and len(text) > 10:
                return result
    except Exception as e:
        print(f"[BRIEFING] Smart version failed, falling back: {e}")

    # Fallback: legacy DB-bullets briefing (was the only thing until now)
    briefing_parts = []
    conn = None

    try:
        conn = get_conn()
        conn.autocommit = True  # so one failed query doesn't abort the next
    except Exception as e:
        print(f"[BRIEFING] Connection failed: {e}")
        return {"ok": True, "briefing": "All clear. What do you need?", "parts": 1}

    # Unread high-priority alerts (skip the push-fallback noise)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT title, body FROM tony_alerts
            WHERE read = FALSE AND priority IN ('urgent', 'high')
            AND created_at > NOW() - INTERVAL '48 hours'
            AND source != 'tony_push'
            AND title NOT LIKE '%Tony — Urgent%'
            ORDER BY created_at DESC LIMIT 3
        """)
        alerts = cur.fetchall()
        cur.close()
        if alerts:
            briefing_parts.append("**Alerts needing your attention:**")
            for title, body in alerts:
                # Clean each line — strip the "Tony — Urgent:" noise if the loop left residue
                clean_body = (body or "").replace("⚠️ Tony — Urgent:", "").strip()
                if len(clean_body) > 120:
                    clean_body = clean_body[:120] + "…"
                briefing_parts.append(f"• **{title}** — {clean_body}" if clean_body else f"• {title}")
    except Exception as e:
        print(f"[BRIEFING] Alerts query: {e}")

    # Pending email approvals
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tony_email_queue WHERE approval_status = 'pending'")
        pending = cur.fetchone()[0]
        cur.close()
        if pending > 0:
            briefing_parts.append(f"**{pending} email(s) waiting for your approval**")
    except Exception as e:
        print(f"[BRIEFING] Email queue: {e}")

    # Active urgent/high goals
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT title, priority FROM tony_goals
            WHERE status = 'active' AND priority IN ('urgent', 'high')
            ORDER BY CASE priority WHEN 'urgent' THEN 1 ELSE 2 END LIMIT 2
        """)
        goals = cur.fetchall()
        cur.close()
        if goals:
            briefing_parts.append("**Active priorities:**")
            for title, pri in goals:
                briefing_parts.append(f"• {title} ({pri})")
    except Exception as e:
        print(f"[BRIEFING] Goals query: {e}")

    # Family dates coming up
    try:
        from datetime import date
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
    except Exception as e:
        print(f"[BRIEFING] Family dates: {e}")

    # Weekly strategy if exists
    try:
        cur = conn.cursor()
        cur.execute("SELECT content FROM tony_living_memory WHERE section = 'WEEKLY_STRATEGY'")
        row = cur.fetchone()
        cur.close()
        if row and row[0] and row[0] != "Not yet assessed.":
            briefing_parts.append(f"**This week:** {row[0][:150]}")
    except Exception as e:
        print(f"[BRIEFING] Weekly strategy: {e}")

    # What Tony did in the last 6 hours — tony_build_log may not exist
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM tony_build_log
            WHERE success = TRUE AND created_at > NOW() - INTERVAL '6 hours'
        """)
        builds = cur.fetchone()[0]
        cur.close()
        if builds > 0:
            briefing_parts.append(f"Tony completed {builds} autonomous tasks while you were away.")
    except Exception:
        pass  # table doesn't exist — silent skip (never user-facing)

    # Capability builds that finished overnight
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT capability_name, capability_description FROM tony_capability_requests
            WHERE status = 'built' AND completed_at > NOW() - INTERVAL '24 hours'
            ORDER BY completed_at DESC LIMIT 3
        """)
        built = cur.fetchall()
        cur.close()
        if built:
            briefing_parts.append("**New capabilities built overnight:**")
            for name, desc in built:
                briefing_parts.append(f"• {name}: {(desc or '')[:80]}")
    except Exception:
        pass

    try:
        conn.close()
    except Exception:
        pass
    
    if not briefing_parts:
        briefing_parts.append("All clear — no urgent items. What do you need?")
    
    return {
        "ok": True,
        "briefing": "\n\n".join(briefing_parts),
        "parts": len(briefing_parts)
    }


@router.get("/proactive/briefing/smart")
async def get_smart_briefing(_=Depends(verify_token)):
    """
    Intelligent briefing — LLM-synthesised single paragraph in Tony's voice.
    Falls back gracefully if anything upstream fails.
    """
    try:
        from app.core.intelligent_briefing import get_intelligent_briefing
        return await get_intelligent_briefing()
    except Exception as e:
        return {"ok": False, "error": str(e),
                "briefing": "Tony's briefing engine had an issue. What do you need?"}


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
