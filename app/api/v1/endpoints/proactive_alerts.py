"""
Proactive alerts endpoint — Matthew's pending alerts.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token

router = APIRouter()


@router.get("/proactive_alerts")
async def get_proactive_alerts(_=Depends(verify_token)):
    """Get all unread proactive alerts."""
    try:
        from app.core.proactive import get_unread_alerts
        alerts = get_unread_alerts()
        return {"ok": True, "alerts": alerts, "count": len(alerts)}
    except Exception as e:
        return {"ok": False, "alerts": [], "error": str(e)}


@router.post("/proactive_alerts/{alert_id}/read")
async def mark_alert_read(alert_id: int, _=Depends(verify_token)):
    """Mark a specific alert as read."""
    try:
        from app.core.proactive import mark_alert_read
        mark_alert_read(alert_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/proactive_alerts/read-all")
async def mark_all_read(_=Depends(verify_token)):
    """Mark all alerts as read."""
    try:
        import psycopg2, os
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("UPDATE tony_alerts SET read = TRUE WHERE read = FALSE")
        conn.commit()
        cur.close()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
