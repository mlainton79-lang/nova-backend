"""Operator interface — the contract every platform-specific operator implements.

The operator is context-free: it's a class instance with async methods that can
be called from any process (FastAPI request handler, background asyncio task,
cron worker, etc.). Where it runs is a deployment decision, not part of the
operator's identity.

Status lifecycle (the cross-platform contract):
    queued → starting → submitting →
      [posted_pending_confirmation → posted_confirmed]
      OR [awaiting_human_approval → submitting (resume) → ...]
      OR [failed]
      OR [cancelled]

Every operator method MUST NEVER raise — failure paths must set
status='failed' on the job (via app.selling.jobs.update_status) and call
record_run_event(subsystem=f'selling.{platform}', ...) before returning False.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Operator(Protocol):
    """Every platform operator implements this interface."""

    platform: str  # e.g. 'ebay', 'discogs', 'vinted', 'musicmagpie'

    async def submit(self, job_id: int) -> bool:
        """Submit the listing to the platform.

        Reads the job row from tony_selling_jobs, fetches/processes images
        from metadata_json['images'], performs platform-specific API calls,
        updates job status as it progresses (queued → starting → submitting →
        posted_pending_confirmation), and returns True on success, False on
        failure (with status='failed' + error_message set on the row).
        """
        ...

    async def confirm_posted(self, job_id: int) -> bool:
        """Verify the listing is actually live on the platform.

        Polls the platform's listing API to confirm the listing is in an
        ACTIVE state, then transitions status from
        posted_pending_confirmation → posted_confirmed.
        Returns True if confirmed, False if not-yet or failed.
        """
        ...

    async def cancel(self, job_id: int) -> bool:
        """Cancel an in-progress or posted listing.

        Sets status='cancelled' on the job row; for posted listings, also
        ends the listing on the platform if possible (eBay endItem,
        Discogs delete-listing, etc.). Returns True on success.
        """
        ...
