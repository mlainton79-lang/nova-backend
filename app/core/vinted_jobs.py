"""
Vinted job lifecycle — backend module.

Mirrors pending_actions.py shape: lazy idempotent table init, simple
helpers per action. The Playwright worker (vinted_worker/operator.py)
imports this module to read job state and write status/event updates.
The /api/v1/vinted/jobs endpoints also use it.

Two tables:
  tony_vinted_jobs        — one row per job, current state
  tony_vinted_job_events  — append-only audit log
"""
import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_vinted_jobs_tables():
    """Idempotent — called lazily before each operation."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_vinted_jobs (
                id SERIAL PRIMARY KEY,
                draft_id TEXT,
                source_android_draft_id TEXT,
                item_name TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                account TEXT DEFAULT 'default',
                current_step TEXT,
                progress_pct INT DEFAULT 0,
                last_screenshot_path TEXT,
                final_screenshot_path TEXT,
                error_message TEXT,
                error_type TEXT,
                requires_human_reason TEXT,
                approval_state TEXT DEFAULT 'not_required',
                approved_at TIMESTAMPTZ,
                posted_confirmed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                cancelled_at TIMESTAMPTZ,
                metadata_json JSONB DEFAULT '{}'::jsonb
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_vinted_job_events (
                id SERIAL PRIMARY KEY,
                job_id INT REFERENCES tony_vinted_jobs(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                message TEXT,
                screenshot_path TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                metadata_json JSONB DEFAULT '{}'::jsonb
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_vinted_jobs_status_created
            ON tony_vinted_jobs (status, created_at DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_vinted_job_events_job
            ON tony_vinted_job_events (job_id, created_at DESC)
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[VINTED_JOBS] init failed: {e}")


def create_job(
    item_name: str,
    metadata: Dict[str, Any],
    draft_id: Optional[str] = None,
    source_android_draft_id: Optional[str] = None,
    account: str = "default",
) -> Optional[int]:
    """Create a new job row. Returns id or None on error."""
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_vinted_jobs (
                draft_id, source_android_draft_id, item_name,
                account, status, metadata_json, created_at
            ) VALUES (%s, %s, %s, %s, 'queued', %s, NOW())
            RETURNING id
        """, (
            draft_id,
            source_android_draft_id,
            item_name,
            account,
            psycopg2.extras.Json(metadata or {}),
        ))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return new_id
    except Exception as e:
        print(f"[VINTED_JOBS] create_job failed: {e}")
        return None


def _row_to_dict(row, cols) -> Dict:
    out = {}
    for i, c in enumerate(cols):
        v = row[i]
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[c] = v
    return out


_JOB_COLUMNS = [
    "id", "draft_id", "source_android_draft_id", "item_name",
    "status", "account", "current_step", "progress_pct",
    "last_screenshot_path", "final_screenshot_path",
    "error_message", "error_type",
    "requires_human_reason", "approval_state",
    "approved_at", "posted_confirmed_at",
    "created_at", "started_at", "completed_at", "cancelled_at",
    "metadata",
]


def get_job(job_id: int) -> Optional[Dict]:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, draft_id, source_android_draft_id, item_name,
                   status, account, current_step, progress_pct,
                   last_screenshot_path, final_screenshot_path,
                   error_message, error_type,
                   requires_human_reason, approval_state,
                   approved_at, posted_confirmed_at,
                   created_at, started_at, completed_at, cancelled_at,
                   metadata_json
            FROM tony_vinted_jobs WHERE id = %s
        """, (job_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return _row_to_dict(row, _JOB_COLUMNS)
    except Exception as e:
        print(f"[VINTED_JOBS] get_job failed: {e}")
        return None


def list_recent_jobs(limit: int = 20, status: Optional[str] = None) -> List[Dict]:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT id, draft_id, source_android_draft_id, item_name,
                       status, account, current_step, progress_pct,
                       last_screenshot_path, final_screenshot_path,
                       error_message, error_type,
                       requires_human_reason, approval_state,
                       approved_at, posted_confirmed_at,
                       created_at, started_at, completed_at, cancelled_at,
                       metadata_json
                FROM tony_vinted_jobs
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (status, limit))
        else:
            cur.execute("""
                SELECT id, draft_id, source_android_draft_id, item_name,
                       status, account, current_step, progress_pct,
                       last_screenshot_path, final_screenshot_path,
                       error_message, error_type,
                       requires_human_reason, approval_state,
                       approved_at, posted_confirmed_at,
                       created_at, started_at, completed_at, cancelled_at,
                       metadata_json
                FROM tony_vinted_jobs
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_dict(r, _JOB_COLUMNS) for r in rows]
    except Exception as e:
        print(f"[VINTED_JOBS] list_recent_jobs failed: {e}")
        return []


def update_status(
    job_id: int,
    status: str,
    started: bool = False,
    completed: bool = False,
    cancelled: bool = False,
    error_message: Optional[str] = None,
    error_type: Optional[str] = None,
    final_screenshot_path: Optional[str] = None,
    last_screenshot_path: Optional[str] = None,
) -> bool:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        sets = ["status = %s"]
        params: List[Any] = [status]

        if started:
            sets.append("started_at = COALESCE(started_at, NOW())")
        if completed:
            sets.append("completed_at = NOW()")
        if cancelled:
            sets.append("cancelled_at = NOW()")
        if error_message is not None:
            sets.append("error_message = %s")
            params.append(error_message)
        if error_type is not None:
            sets.append("error_type = %s")
            params.append(error_type)
        if final_screenshot_path is not None:
            sets.append("final_screenshot_path = %s")
            params.append(final_screenshot_path)
        if last_screenshot_path is not None:
            sets.append("last_screenshot_path = %s")
            params.append(last_screenshot_path)

        params.append(job_id)
        cur.execute(
            f"UPDATE tony_vinted_jobs SET {', '.join(sets)} WHERE id = %s",
            params,
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[VINTED_JOBS] update_status failed: {e}")
        return False


def append_event(
    job_id: int,
    event_type: str,
    message: Optional[str] = None,
    screenshot_path: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> bool:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_vinted_job_events
                (job_id, event_type, message, screenshot_path, metadata_json)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            job_id,
            event_type,
            message,
            screenshot_path,
            psycopg2.extras.Json(metadata or {}),
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[VINTED_JOBS] append_event failed: {e}")
        return False


def list_recent_events(job_id: int, limit: int = 50) -> List[Dict]:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_type, message, screenshot_path, created_at
            FROM tony_vinted_job_events
            WHERE job_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (job_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0],
                "event_type": r[1],
                "message": r[2],
                "screenshot_path": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[VINTED_JOBS] list_recent_events failed: {e}")
        return []


def mark_requires_human(job_id: int, reason: str) -> bool:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_vinted_jobs
            SET status = 'requires_human',
                requires_human_reason = %s
            WHERE id = %s
        """, (reason, job_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[VINTED_JOBS] mark_requires_human failed: {e}")
        return False


def mark_published_by_matthew(job_id: int) -> bool:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_vinted_jobs
            SET status = 'published_by_matthew',
                posted_confirmed_at = NOW(),
                completed_at = NOW()
            WHERE id = %s
        """, (job_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[VINTED_JOBS] mark_published_by_matthew failed: {e}")
        return False


def mark_cancelled(job_id: int) -> bool:
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_vinted_jobs
            SET status = 'cancelled',
                cancelled_at = NOW(),
                completed_at = NOW()
            WHERE id = %s
        """, (job_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[VINTED_JOBS] mark_cancelled failed: {e}")
        return False


def get_active_for_account(account: str = "default") -> Optional[Dict]:
    """Returns the most recent non-terminal job for an account, or None."""
    init_vinted_jobs_tables()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, draft_id, source_android_draft_id, item_name,
                   status, account, current_step, progress_pct,
                   last_screenshot_path, final_screenshot_path,
                   error_message, error_type,
                   requires_human_reason, approval_state,
                   approved_at, posted_confirmed_at,
                   created_at, started_at, completed_at, cancelled_at,
                   metadata_json
            FROM tony_vinted_jobs
            WHERE account = %s
              AND status NOT IN ('published_by_matthew', 'cancelled', 'error', 'safety_violation')
            ORDER BY created_at DESC
            LIMIT 1
        """, (account,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return _row_to_dict(row, _JOB_COLUMNS)
    except Exception as e:
        print(f"[VINTED_JOBS] get_active_for_account failed: {e}")
        return None
