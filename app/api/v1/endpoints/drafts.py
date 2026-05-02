"""
Tony's email drafts endpoint.
Matthew can view, send, or dismiss Tony's prepared draft replies.
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.email_drafter import (
    get_pending_drafts, get_draft_for_send,
    mark_draft_sent, mark_draft_dismissed, update_draft_fields,
    scan_and_draft_replies, init_draft_tables
)
from app.core.gmail_service import send_email

router = APIRouter()


class SendDraftRequest(BaseModel):
    """
    Optional Matthew-edited overrides for a stored draft. Trust anchors
    (account, recipient, original_message_id) are NEVER read from this body —
    they come from the DB row only. Subject/body may be edited.
    """
    final_subject: Optional[str] = None
    final_body: Optional[str] = None


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
async def send_draft(
    draft_id: int,
    overrides: SendDraftRequest = SendDraftRequest(),
    _=Depends(verify_token),
):
    """
    Send one of Tony's prepared drafts.

    Trust anchors (account, recipient, original_message_id) come from the
    stored draft row. Optional `final_subject` / `final_body` in the request
    body let Matthew send an edited version without losing the audit chain.
    """
    draft = get_draft_for_send(draft_id)
    if not draft:
        return {"ok": False, "error": "Draft not found or already actioned"}

    effective_subject = (
        overrides.final_subject
        if overrides.final_subject is not None and overrides.final_subject.strip()
        else draft["draft_subject"]
    )
    effective_body = (
        overrides.final_body
        if overrides.final_body is not None and overrides.final_body.strip()
        else draft["draft_body"]
    )

    sent = await send_email(
        email=draft["account"],            # trust anchor — DB
        to=draft["draft_to"],              # trust anchor — DB
        subject=effective_subject,
        body=effective_body,
        reply_to_id=draft.get("original_message_id"),  # trust anchor — DB
    )

    if sent:
        # Persist the final approved subject/body so the audit row reflects
        # what was actually sent, not what was originally drafted.
        update_draft_fields(
            draft_id,
            draft_subject=effective_subject,
            draft_body=effective_body,
        )
        mark_draft_sent(draft_id)
        from app.core.self_eval import verify_email_sent
        await verify_email_sent(draft["draft_to"], effective_subject, draft["account"])
        return {"ok": True, "message": "Draft sent and verified"}
    else:
        return {"ok": False, "error": "Send failed — check Gmail auth"}


@router.post("/drafts/{draft_id}/dismiss")
async def dismiss_draft(draft_id: int, _=Depends(verify_token)):
    """Dismiss a draft Tony prepared."""
    mark_draft_dismissed(draft_id)
    return {"ok": True, "message": "Draft dismissed"}
