"""Push notification endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.security import verify_token
from app.core.push_notifications import (
    save_push_token, get_push_token,
    send_push, tony_notify, store_config,
)

router = APIRouter()

def _resolve_push_registration(
    query_token: str | None,
    query_platform: str | None,
    body: object,
) -> tuple[str, str]:
    payload = body if isinstance(body, dict) else {}
    candidate = query_token if query_token is not None else payload.get("token")
    if not isinstance(candidate, str) or not candidate.strip():
        raise HTTPException(status_code=422, detail="A non-empty token is required")

    platform_candidate = (
        query_platform if query_platform is not None else payload.get("platform")
    )
    resolved_platform = (
        platform_candidate.strip()
        if isinstance(platform_candidate, str) and platform_candidate.strip()
        else "android"
    )
    return candidate.strip(), resolved_platform


@router.post("/push/register")
async def register_token(
    request: Request,
    token: str | None = None,
    platform: str | None = None,
    _: bool = Depends(verify_token),
):
    try:
        body = await request.json()
    except ValueError:
        body = {}

    resolved_token, resolved_platform = _resolve_push_registration(
        token, platform, body
    )
    save_push_token(resolved_token, resolved_platform)
    return {"ok": True, "message": "Push token registered"}

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


@router.post("/push/test-latest")
async def test_latest_push(_=Depends(verify_token)):
    """Send one fixed test notification to the latest registered device."""
    if not get_push_token():
        return {
            "ok": False,
            "status": "no_token",
            "message": "No push token registered",
        }

    ok = await send_push("Nova test", "Push notifications are connected.")
    return {
        "ok": ok,
        "status": "sent" if ok else "send_failed",
        "message": "Test notification sent" if ok else "Test notification failed",
    }


@router.post("/push/setup-firebase")
async def setup_firebase(service_account_json: str, _=Depends(verify_token)):
    """Store Firebase service account credentials in DB."""
    import json
    try:
        json.loads(service_account_json)  # validate it's valid JSON
    except Exception:
        return {"ok": False, "error": "Invalid JSON"}
    ok = store_config("firebase_service_account", service_account_json)
    return {"ok": ok, "message": "Firebase credentials stored" if ok else "Storage failed"}

@router.get("/push/status")
async def push_status(_=Depends(verify_token)):
    """Check push notification status.

    P2.1 from the 2026-05-28 audit: this used to check the legacy
    FIREBASE_SERVER_KEY env var, which has been obsolete since the FCM V1
    migration (commit aa7e0f1). Push actually reads credentials via
    get_firebase_credentials() which tries FIREBASE_SERVICE_ACCOUNT env var
    then falls back to tony_config DB. Status check now mirrors that.
    """
    from app.core.push_notifications import get_firebase_credentials
    token = get_push_token()
    firebase_configured = bool(get_firebase_credentials())
    return {
        "token_registered": bool(token),
        "firebase_configured": firebase_configured,
        "status": "ready" if (token and firebase_configured) else (
            "needs_firebase_config" if not firebase_configured
            else "needs_token_registration"
        ),
    }
