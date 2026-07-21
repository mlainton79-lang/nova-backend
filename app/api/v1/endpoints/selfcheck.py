"""On-demand self-check endpoint.

Read-only by construction (gather_self_check is passive database reads),
so it accepts the diag scope: a leaked DIAG_TOKEN can learn that Gmail
tokens are stale, never refresh them.
"""
from fastapi import APIRouter, Depends

from app.core.security import verify_read_token
from app.core.self_check import format_self_check, gather_self_check, self_check_headline

router = APIRouter()


@router.get("/selfcheck")
async def selfcheck(_scope=Depends(verify_read_token)):
    status = gather_self_check()
    return {
        "headline": self_check_headline(status),
        "text": format_self_check(status),
        "checks": status,
    }
