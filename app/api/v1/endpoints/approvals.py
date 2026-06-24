"""Protected approval inbox endpoints."""

from fastapi import APIRouter, Depends, Query

from app.core.approval_lock import list_active_pending_approvals
from app.core.security import verify_token


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
