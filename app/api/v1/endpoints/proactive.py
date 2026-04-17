"""
Tony's proactive alerts endpoints.
Tony surfaces what Matthew needs to know without being asked.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.proactive import (
    get_unread_alerts, mark_alert_read,
    create_alert, run_proactive_scan
)

router = APIRouter()

@router.get("/alerts")
async def get_alerts(_=Depends(verify_token)):
    """Get all unread alerts Tony has created for Matthew."""
    alerts = get_unread_alerts()
    return {
        "alerts": alerts,
        "count": len(alerts),
        "urgent": len([a for a in alerts if a["priority"] in ("urgent", "high")])
    }

@router.post("/alerts/{alert_id}/read")
async def read_alert(alert_id: int, _=Depends(verify_token)):
    """Mark an alert as read."""
    mark_alert_read(alert_id)
    return {"ok": True}

@router.post("/alerts/scan")
async def trigger_scan(_=Depends(verify_token)):
    """Tony scans everything now and creates alerts for anything urgent."""
    result = await run_proactive_scan()
    return result

@router.get("/alerts/test")
async def alerts_test(_=Depends(verify_token)):
    """Create a test alert to verify the system works."""
    alert_id = create_alert(
        alert_type="test",
        title="Tony's proactive system is active",
        body="Tony is now monitoring your world and will surface important things without being asked.",
        priority="normal",
        source="system"
    )
    return {"ok": True, "alert_id": alert_id}
