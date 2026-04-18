"""Push notification endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.push_notifications import (
    save_push_token, get_push_token,
    send_push, tony_notify, init_push_table
)

router = APIRouter()

@router.post("/push/register")
async def register_token(token: str, platform: str = "android", _=Depends(verify_token)):
    """Register Matthew's device for push notifications."""
    init_push_table()
    save_push_token(token, platform)
    return {"ok": True, "message": "Tony can now reach you directly"}

@router.post("/push/send")
async def send_notification(title: str, body: str, _=Depends(verify_token)):
    """Tony sends a push notification."""
    ok = await send_push(title, body)
    return {"ok": ok}

@router.post("/push/test")
async def test_push(_=Depends(verify_token)):
    """Test push notification."""
    ok = await tony_notify("Tony is here. Push notifications are working.")
    return {"ok": ok, "token_registered": bool(get_push_token())}

@router.get("/push/status")
async def push_status(_=Depends(verify_token)):
    """Check push notification status."""
    token = get_push_token()
    return {
        "token_registered": bool(token),
        "firebase_configured": bool(__import__('os').environ.get("FIREBASE_SERVER_KEY")),
        "status": "ready" if token else "needs_token_registration"
    }
