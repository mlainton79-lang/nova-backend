"""
Tony's email drafts endpoint.
Matthew can view, send, or dismiss Tony's prepared draft replies.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.email_drafter import (
    get_pending_drafts, mark_draft_sent, mark_draft_dismissed,
    scan_and_draft_replies, init_draft_tables
)
from app.core.gmail_service import send_email

router = APIRouter()


@router.get("/drafts")
async def list_drafts(_=Depends(verify_token)):
    """Get all draft replies Tony has prepared."""
    init_draft_tables()
    drafts = get_pending_drafts()
    return {"ok": True, "drafts": drafts, "count": len(drafts)}


@router.post("/drafts/scan")
async def trigger_draft_scan(_=Depends(verify_token)):
    """Manually trigger Tony to scan inbox and prepare draft replies."""
    init_draft_tables()
    result = await scan_and_draft_replies()
    return {"ok": True, **result}


@router.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: int, _=Depends(verify_token)):
    """Send one of Tony's prepared drafts."""
    drafts = get_pending_drafts()
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        return {"ok": False, "error": "Draft not found or already actioned"}

    sent = await send_email(
        email=draft["account"],
        to=draft["draft_to"],
        subject=draft["draft_subject"],
        body=draft["draft_body"]
    )

    if sent:
        mark_draft_sent(draft_id)
        # Verify it was actually sent
        from app.core.self_eval import verify_email_sent
        await verify_email_sent(draft["draft_to"], draft["draft_subject"], draft["account"])
        return {"ok": True, "message": "Draft sent and verified"}
    else:
        return {"ok": False, "error": "Send failed — check Gmail auth"}


@router.post("/drafts/{draft_id}/dismiss")
async def dismiss_draft(draft_id: int, _=Depends(verify_token)):
    """Dismiss a draft Tony prepared."""
    mark_draft_dismissed(draft_id)
    return {"ok": True, "message": "Draft dismissed"}
