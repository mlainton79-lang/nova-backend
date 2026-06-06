"""
Admin worker-log read endpoint.

Read-only view over tony_worker_log so the overnight cron's per-task
outcomes can be inspected via HTTP instead of via a DB shell. Sibling to
admin_clear.py — same auth model, same get_conn helper pattern.

SELECT only. No writes, no schema changes, no new dependencies.
"""
import os
from datetime import datetime

import psycopg2
from fastapi import APIRouter, Depends, Query

from app.core.security import verify_token
from app.observability import EVENT_TYPES, EventSeverity, record_run_event


router = APIRouter()

_MAX_HOURS = 168
_DETAIL_PREVIEW = 120
_ROW_HARD_LIMIT = 1000


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@router.get("/admin/worker_log/recent")
async def worker_log_recent(
    hours: int = Query(24, ge=1, le=_MAX_HOURS),
    _=Depends(verify_token),
):
    """Return tony_worker_log rows from the last `hours` hours."""
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT task_name, success, duration_seconds, detail, ran_at
            FROM tony_worker_log
            WHERE ran_at > NOW() - %s * INTERVAL '1 hour'
            ORDER BY ran_at DESC
            LIMIT %s
            """,
            (hours, _ROW_HARD_LIMIT),
        )
        raw = cur.fetchall()
        cur.close()
        # tony_journal counts — best-effort, independent of worker-log read.
        # A missing/broken journal table must not block the primary worker-log
        # diagnostics, which is what this endpoint exists for.
        journal = None
        try:
            jcur = conn.cursor()
            jcur.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (
                        WHERE created_at > NOW() - %s * INTERVAL '1 hour'
                    ),
                    MAX(created_at)
                FROM tony_journal
                """,
                (hours,),
            )
            j_total, j_in_window, j_latest = jcur.fetchone()
            jcur.close()
            journal = {
                "total": j_total,
                "in_window": j_in_window,
                "latest_at": _iso(j_latest),
            }
        except Exception as je:
            record_run_event(
                event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
                severity=EventSeverity.WARNING,
                subsystem="admin.worker_log.journal",
                message="tony_journal count query failed",
                error_class=type(je).__name__,
                error_message=str(je),
                metadata={"hours": hours},
            )
            journal = {"error": str(je)}
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.WARNING,
            subsystem="admin.worker_log",
            message="worker_log_recent query failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"hours": hours},
        )
        return {"ok": False, "error": str(e), "hours": hours}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    rows = []
    passed = 0
    failed = 0
    for task_name, success, duration_seconds, detail, ran_at in raw:
        detail_text = (detail or "").strip()
        preview = detail_text[:_DETAIL_PREVIEW]
        rows.append({
            "task_name": task_name,
            "success": bool(success) if success is not None else None,
            "duration_seconds": duration_seconds,
            "ran_at": _iso(ran_at),
            "detail_preview": preview,
            "detail_truncated": len(detail_text) > _DETAIL_PREVIEW,
        })
        if success is True:
            passed += 1
        elif success is False:
            failed += 1

    return {
        "ok": True,
        "hours": hours,
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "rows": rows,
        "journal": journal,
    }
