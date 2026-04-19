"""Email agent endpoint."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.email_agent import (
    get_pending_approvals, approve_and_send, scan_for_actionable_emails,
    init_email_agent_tables
)

router = APIRouter()


@router.get("/email-agent/pending")
async def get_pending(_=Depends(verify_token)):
    """Get emails queued for Matthew's approval."""
    return {"emails": await get_pending_approvals()}


@router.post("/email-agent/approve/{queue_id}")
async def approve_email(queue_id: int, _=Depends(verify_token)):
    """Matthew approves — Tony sends the email."""
    sent = await approve_and_send(queue_id)
    return {"ok": sent, "sent": sent}


@router.post("/email-agent/scan")
async def scan_emails(_=Depends(verify_token)):
    """Scan for actionable emails and queue drafts."""
    results = await scan_for_actionable_emails()
    return {"ok": True, "actionable_found": len(results), "results": results}
