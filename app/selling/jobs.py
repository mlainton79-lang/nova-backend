"""Job model for tony_selling_jobs + tony_selling_job_events.

CRUD operations against the two tables created by migration
db/migrations/20260524160000_create_selling_jobs.sql. Pattern:
- Per-call psycopg2.connect, sslmode='require' (matches run_ledger.py convention)
- MUST NEVER raise — every public function catches Exception and records a
  run_events row via record_run_event(subsystem='selling.jobs', ...), then
  returns None / False / [] as appropriate
- Auto-stamps lifecycle timestamps based on the new status in update_status()
"""

import os
import json
from enum import Enum
from typing import Optional, Dict, List, Any

import psycopg2
import psycopg2.extras

from app.observability import record_run_event, EventSeverity, EVENT_TYPES


class JobStatus(str, Enum):
    """Cross-platform status lifecycle. Matches the CHECK constraint on tony_selling_jobs.status."""
    QUEUED = "queued"
    STARTING = "starting"
    SUBMITTING = "submitting"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    POSTED_PENDING_CONFIRMATION = "posted_pending_confirmation"
    POSTED_CONFIRMED = "posted_confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_VALID_STATUSES = frozenset(s.value for s in JobStatus)
_VALID_PLATFORMS = frozenset({"ebay", "discogs", "vinted", "musicmagpie", "wob", "other"})


def _get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10)


_JOB_COLUMNS = [
    "id", "platform", "account", "item_name", "status",
    "platform_listing_id", "platform_listing_url",
    "error_message", "error_type", "requires_human_reason",
    "approval_state", "approved_at", "posted_confirmed_at",
    "created_at", "started_at", "completed_at", "cancelled_at",
    "metadata_json",
]


def _row_to_dict(row) -> Dict[str, Any]:
    out = {}
    for i, c in enumerate(_JOB_COLUMNS):
        v = row[i]
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[c] = v
    return out


def create_job(
    platform: str,
    item_name: str,
    account: str = "default",
    metadata: Optional[dict] = None,
) -> Optional[int]:
    """Insert a new tony_selling_jobs row with status='queued'.

    Returns the new id on success, None on any failure.
    """
    try:
        if platform not in _VALID_PLATFORMS:
            record_run_event(
                event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
                severity=EventSeverity.ERROR,
                subsystem="selling.jobs",
                message=f"create_job called with invalid platform={platform!r}",
                metadata={"platform": platform, "item_name": item_name[:120]},
            )
            return None
        meta = metadata or {}
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tony_selling_jobs (
                        platform, account, item_name, status, metadata_json
                    ) VALUES (%s, %s, %s, 'queued', %s::jsonb)
                    RETURNING id
                    """,
                    (platform, account, item_name, json.dumps(meta, default=str)),
                )
                return int(cur.fetchone()[0])
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.jobs",
            message="create_job failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"platform": platform, "item_name": (item_name or "")[:120]},
        )
        return None


def get_job(job_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a job by id. Returns dict on success, None if not found or on error."""
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_JOB_COLUMNS)} FROM tony_selling_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                return _row_to_dict(row) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.jobs",
            message="get_job failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"job_id": job_id},
        )
        return None


def update_status(
    job_id: int,
    new_status: str,
    error_message: Optional[str] = None,
    error_type: Optional[str] = None,
    requires_human_reason: Optional[str] = None,
    platform_listing_id: Optional[str] = None,
    platform_listing_url: Optional[str] = None,
) -> bool:
    """Update job status + optional fields. Auto-stamps lifecycle timestamps.

    Stamps:
      new_status='starting'                   → started_at = NOW()
      new_status='posted_confirmed'           → completed_at = NOW(), posted_confirmed_at = NOW()
      new_status in ('failed','cancelled')    → completed_at = NOW(), cancelled_at = NOW() (for cancelled)

    Returns True on success, False on any failure (DB error, invalid status, row not found).
    """
    try:
        if new_status not in _VALID_STATUSES:
            record_run_event(
                event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
                severity=EventSeverity.ERROR,
                subsystem="selling.jobs",
                message=f"update_status called with invalid new_status={new_status!r}",
                metadata={"job_id": job_id, "new_status": new_status},
            )
            return False

        # Build SET clauses dynamically based on which fields are non-None and status transitions
        sets = ["status = %s"]
        params: List[Any] = [new_status]
        if error_message is not None:
            sets.append("error_message = %s")
            params.append(error_message)
        if error_type is not None:
            sets.append("error_type = %s")
            params.append(error_type)
        if requires_human_reason is not None:
            sets.append("requires_human_reason = %s")
            params.append(requires_human_reason)
        if platform_listing_id is not None:
            sets.append("platform_listing_id = %s")
            params.append(platform_listing_id)
        if platform_listing_url is not None:
            sets.append("platform_listing_url = %s")
            params.append(platform_listing_url)
        # Lifecycle timestamp stamping
        if new_status == "starting":
            sets.append("started_at = NOW()")
        if new_status == "posted_confirmed":
            sets.append("completed_at = NOW()")
            sets.append("posted_confirmed_at = NOW()")
        if new_status == "failed":
            sets.append("completed_at = NOW()")
        if new_status == "cancelled":
            sets.append("completed_at = NOW()")
            sets.append("cancelled_at = NOW()")

        params.append(job_id)
        sql = f"UPDATE tony_selling_jobs SET {', '.join(sets)} WHERE id = %s"

        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return cur.rowcount > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.jobs",
            message="update_status failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"job_id": job_id, "new_status": new_status},
        )
        return False


def append_event(
    job_id: int,
    event_type: str,
    message: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[int]:
    """Append an audit-log event for a job. Returns the event id on success, None on failure."""
    try:
        meta = metadata or {}
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tony_selling_job_events (job_id, event_type, message, metadata_json)
                    VALUES (%s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (job_id, event_type, message, json.dumps(meta, default=str)),
                )
                return int(cur.fetchone()[0])
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.jobs",
            message="append_event failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"job_id": job_id, "event_type": event_type},
        )
        return None


def list_jobs(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """List jobs filtered by platform and/or status. Returns [] on any failure."""
    try:
        wheres = []
        params: List[Any] = []
        if platform is not None:
            wheres.append("platform = %s")
            params.append(platform)
        if status is not None:
            wheres.append("status = %s")
            params.append(status)
        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        params.append(int(limit))

        sql = (
            f"SELECT {', '.join(_JOB_COLUMNS)} FROM tony_selling_jobs "
            f"{where_clause} ORDER BY id DESC LIMIT %s"
        )
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return [_row_to_dict(r) for r in cur.fetchall()]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.jobs",
            message="list_jobs failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"platform": platform, "status": status, "limit": limit},
        )
        return []
