"""WhatsApp endpoint — Tony sends proactive messages."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.whatsapp import send_whatsapp, tony_whatsapp_notify, is_configured

router = APIRouter()


class WhatsAppRequest(BaseModel):
    message: str
    priority: str = "normal"


@router.post("/whatsapp/send")
async def send_message(req: WhatsAppRequest, _=Depends(verify_token)):
    """Send a WhatsApp message to Matthew."""
    if not is_configured():
        return {
            "ok": False,
            "error": "Twilio not configured. Add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to Railway variables.",
            "setup_needed": True
        }
    ok = await tony_whatsapp_notify("Tony", req.message, req.priority)
    return {"ok": ok}


@router.get("/whatsapp/status")
async def whatsapp_status(_=Depends(verify_token)):
    """Check WhatsApp configuration status."""
    import os
    return {
        "configured": is_configured(),
        "matthew_number": os.environ.get("MATTHEW_WHATSAPP", "not set"),
        "from_number": os.environ.get("TWILIO_WHATSAPP_FROM", "not set"),
        "note": "Add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to Railway to enable"
    }


@router.post("/whatsapp/test")
async def test_whatsapp(_=Depends(verify_token)):
    """Send a test WhatsApp message."""
    ok = await send_whatsapp("Tony here. WhatsApp is working. I'll message you when something needs your attention.")
    return {"ok": ok, "configured": is_configured()}
