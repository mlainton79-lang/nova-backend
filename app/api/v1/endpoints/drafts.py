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
    mark_draft_dismissed, update_draft_fields,
    scan_and_draft_replies, _send_draft_internal,
)

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
    drafts = get_pending_drafts()
    return {"ok": True, "drafts": drafts, "count": len(drafts)}


@router.post("/drafts/scan")
async def trigger_draft_scan(_=Depends(verify_token)):
    """Manually trigger Tony to scan inbox and prepare draft replies."""
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

    Override flow (UI tap with edits):
      1. Persist the edits to the row via update_draft_fields(). Status-guard
         means it only takes if the row is still 'pending'. If persistence
         fails (DB blip, concurrent claim) we DO NOT send — otherwise we'd
         send the pre-edit DB content while the audit row would lie.
      2. Then call _send_draft_internal() which atomically claims the row,
         calls Gmail using trust anchors from the DB, and marks sent or
         reverts on failure.

    The chat approval-gate path goes through the same _send_draft_internal()
    helper with an expected_hash; the HTTP path passes None (this endpoint
    is its own authorisation).
    """
    has_subject_override = bool(overrides.final_subject and overrides.final_subject.strip())
    has_body_override = bool(overrides.final_body and overrides.final_body.strip())

    if has_subject_override or has_body_override:
        existing = get_draft_for_send(draft_id)
        if not existing:
            return {"ok": False, "error": "Draft not found or already actioned"}

        effective_subject = (
            overrides.final_subject.strip() if has_subject_override
            else existing["draft_subject"]
        )
        effective_body = (
            overrides.final_body.strip() if has_body_override
            else existing["draft_body"]
        )

        persisted = update_draft_fields(draft_id, effective_subject, effective_body)
        if not persisted:
            return {
                "ok": False,
                "error": (
                    "Couldn't persist edits — draft may have been claimed for "
                    "sending or is no longer pending."
                ),
            }

    result = await _send_draft_internal(draft_id, expected_hash=None)

    if result.get("ok"):
        return {"ok": True, "message": "Draft sent"}

    reason = result.get("reason", "unknown")
    if reason == "not_pending":
        return {"ok": False, "error": "Draft not found or already actioned"}
    if reason == "send_failed":
        return {"ok": False, "error": "Send failed — check Gmail auth"}
    if reason == "audit_anomaly":
        # Email left Gmail but mark_draft_sent didn't take. Tell the UI it
        # sent so the user isn't blocked; the audit anomaly is logged
        # loudly by _send_draft_internal.
        return {"ok": True, "message": "Draft sent (audit follow-up needed)"}
    return {"ok": False, "error": f"Couldn't send: {reason}"}


@router.post("/drafts/{draft_id}/dismiss")
async def dismiss_draft(draft_id: int, _=Depends(verify_token)):
    """Dismiss a draft Tony prepared."""
    mark_draft_dismissed(draft_id)
    return {"ok": True, "message": "Draft dismissed"}
