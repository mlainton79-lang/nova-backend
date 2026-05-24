"""Nova selling — multi-platform selling operator pattern.

Job model + per-platform operator stubs. Today's scope: scaffolding only;
real eBay implementation lands in session 2+. The vinted-via-Playwright
path in app/core/vinted_jobs.py is the dead-on-arrival predecessor — left
in repo as reference for what we pivoted from.

Public surface:
- create_job, get_job, update_status, append_event, list_jobs — the job CRUD layer
- JobStatus — the cross-platform status enum (matches the CHECK constraint on tony_selling_jobs)
- get_operator(platform) — registry lookup; returns None if no operator registered

Status lifecycle (every operator implements this):
    queued → starting → submitting →
      [posted_pending_confirmation → posted_confirmed]
      OR [awaiting_human_approval → submitting (resume)]
      OR [failed]
      OR [cancelled]
"""

from app.selling.jobs import (
    create_job,
    get_job,
    update_status,
    append_event,
    list_jobs,
    JobStatus,
)
from app.selling.operators import get_operator

__all__ = [
    "create_job",
    "get_job",
    "update_status",
    "append_event",
    "list_jobs",
    "JobStatus",
    "get_operator",
]
