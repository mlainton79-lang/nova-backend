"""eBay operator — STUB. Real implementation lands in session 2+.

Every method records a run_events row with event_type='capability_unavailable'
and returns the failure path, so we have observability from the moment the
stub is wired into anything. The real operator will replace this file (or
sit alongside it as `ebay.py` with the stub deleted) once eBay API credentials
are added to Railway Variables on the web service.

Required credentials (NOT yet present, see project_selling_operator_architecture.md):
- EBAY_PROD_CLIENT_ID
- EBAY_PROD_CLIENT_SECRET
- EBAY_PROD_REDIRECT_URI (for OAuth user-token flow)
- EBAY_SANDBOX_* equivalents for development testing
"""

from app.observability import record_run_event, EventSeverity, EVENT_TYPES
from app.selling.jobs import update_status


class EbayOperator:
    """Stub eBay operator. Every method records a row and returns failure."""

    platform = "ebay"

    async def submit(self, job_id: int) -> bool:
        record_run_event(
            event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
            severity=EventSeverity.WARNING,
            subsystem="selling.ebay",
            capability="submit",
            message="eBay operator submit() called but stub-only — no eBay credentials in Railway Variables yet",
            metadata={"job_id": job_id, "stub": True},
        )
        update_status(
            job_id,
            "failed",
            error_message="eBay operator not yet implemented (stub)",
            error_type="not_implemented",
        )
        return False

    async def confirm_posted(self, job_id: int) -> bool:
        record_run_event(
            event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
            severity=EventSeverity.WARNING,
            subsystem="selling.ebay",
            capability="confirm_posted",
            message="eBay operator confirm_posted() called but stub-only",
            metadata={"job_id": job_id, "stub": True},
        )
        return False

    async def cancel(self, job_id: int) -> bool:
        record_run_event(
            event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
            severity=EventSeverity.WARNING,
            subsystem="selling.ebay",
            capability="cancel",
            message="eBay operator cancel() called but stub-only",
            metadata={"job_id": job_id, "stub": True},
        )
        # Cancel is achievable at the DB level even without a real eBay API call,
        # because for a stub-rejected job there's no live eBay listing to end.
        update_status(job_id, "cancelled")
        return True
