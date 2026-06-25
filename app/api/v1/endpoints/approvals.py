"""Protected approval inbox endpoints."""

from fastapi import APIRouter, Depends, Query

from app.core.approval_lock import (
    approve_pending_approval,
    create_pending_approval_once,
    list_active_pending_approvals,
    reject_pending_approval,
)
from app.core.security import verify_token
from app.core.user_notifications import NotificationType, send_user_notification


router = APIRouter()


@router.get("/approvals/pending")
async def get_pending_approvals(
    limit: int = Query(20, ge=1, le=20),
    _=Depends(verify_token),
):
    """List active pending approvals without exposing secrets."""
    pending = list_active_pending_approvals(limit=limit)
    return {
        "ok": True,
        "count": len(pending),
        "pending_approvals": pending,
    }


@router.post("/approvals/test-pending")
async def create_test_pending_approval(
    _=Depends(verify_token),
):
    """Create one harmless, deduplicated approval-inbox test item."""
    created = create_pending_approval_once(
        capability_key="test.approval_inbox",
        action_type="test_pending_approval",
        step_summary="Test approval for Android Approval Inbox display",
        ttl_minutes=10,
    )
    if not created:
        return {
            "ok": True,
            "created": False,
            "status": "not_created",
            "message": "An equivalent active test approval already exists.",
        }

    try:
        notification_sent = await send_user_notification(
            NotificationType.APPROVAL_REQUIRED
        )
    except Exception:
        notification_sent = False

    return {
        "ok": True,
        "created": True,
        "status": "created" if notification_sent else "created_notification_unavailable",
        "message": (
            "Test approval created and notification sent."
            if notification_sent
            else "Test approval created; notification was unavailable."
        ),
    }


@router.post("/approvals/{pending_id}/reject")
async def reject_approval(
    pending_id: str,
    _=Depends(verify_token),
):
    """Deny one awaiting approval without running its associated action."""
    rejected = reject_pending_approval(pending_id)
    return {
        "ok": True,
        "rejected": rejected,
        "status": "rejected" if rejected else "not_found",
        "message": (
            "Pending approval rejected."
            if rejected
            else "No awaiting approval matched that identifier."
        ),
    }


@router.post("/approvals/{pending_id}/approve")
async def approve_approval(
    pending_id: str,
    _=Depends(verify_token),
):
    """Mark one awaiting approval as approved without running its action."""
    approved = approve_pending_approval(pending_id)
    return {
        "ok": True,
        "approved": approved,
        "status": "approved" if approved else "not_found",
        "message": (
            "Pending approval marked approved."
            if approved
            else "No awaiting approval matched that identifier."
        ),
    }
