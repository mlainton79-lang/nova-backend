"""Protected typed notification gateway endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import verify_token
from app.core.user_notifications import NotificationType, send_user_notification


router = APIRouter()


class TestNotificationRequest(BaseModel):
    type: NotificationType = NotificationType.APPROVAL_REQUIRED


@router.post("/notifications/test-latest")
async def test_latest_notification(
    payload: TestNotificationRequest | None = None,
    _=Depends(verify_token),
):
    """Send one whitelisted notification to the latest registered device."""
    notification_type = (
        payload.type if payload is not None else NotificationType.APPROVAL_REQUIRED
    )
    ok = await send_user_notification(notification_type)
    return {
        "ok": ok,
        "status": "sent" if ok else "send_failed",
        "type": notification_type.value,
        "message": "Notification sent" if ok else "Notification failed",
    }
