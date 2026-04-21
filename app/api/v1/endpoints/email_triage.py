"""
Email triage endpoints — smart digest with categorisation + draft replies.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.email_triage import get_smart_digest, triage_emails

router = APIRouter()


@router.get("/triage/digest")
async def smart_digest(_=Depends(verify_token)):
    """Get a full triage digest — what's urgent, what needs a reply, what to skip."""
    return await get_smart_digest()


class TriageBatchRequest(BaseModel):
    use_cache: bool = True


@router.post("/triage/rerun")
async def rerun_triage(req: TriageBatchRequest, _=Depends(verify_token)):
    """Force re-triage of recent unread emails (bypasses cache)."""
    from app.core.gmail_service import get_all_accounts, list_emails
    accounts = get_all_accounts()
    all_emails = []
    for a in accounts:
        try:
            emails = await list_emails(a, query="is:unread newer_than:3d", max_results=20, label="")
            all_emails.extend(emails)
        except Exception:
            pass
    triaged = await triage_emails(all_emails, use_cache=req.use_cache)
    return {"ok": True, "count": len(triaged), "triaged": triaged}
