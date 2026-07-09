"""Durable workflow state for resumable Nova tasks."""

import os
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_workflow_state_table():
    """Idempotent workflow-state table init."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_workflow_state (
                workflow_id TEXT PRIMARY KEY,
                workflow_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                current_step TEXT,
                summary TEXT,
                state_json JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                resumed_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_workflow_state_status_updated
            ON tony_workflow_state (status, updated_at DESC)
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[WORKFLOW_STATE] init failed: {e}")


def _row_to_workflow(row) -> Dict[str, Any]:
    keys = (
        "workflow_id",
        "workflow_type",
        "status",
        "current_step",
        "summary",
        "state",
        "created_at",
        "updated_at",
        "resumed_at",
        "completed_at",
    )
    out = {}
    for index, key in enumerate(keys):
        value = row[index]
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        out[key] = value
    return out


def upsert_workflow_state(
    *,
    workflow_id: str,
    workflow_type: str,
    status: str = "running",
    current_step: Optional[str] = None,
    summary: Optional[str] = None,
    state: Optional[Dict[str, Any]] = None,
) -> bool:
    """Create or update one durable workflow state row. Never raises."""
    if not workflow_id or not workflow_type:
        return False
    init_workflow_state_table()
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_workflow_state (
                workflow_id, workflow_type, status, current_step, summary,
                state_json, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (workflow_id) DO UPDATE SET
                workflow_type = EXCLUDED.workflow_type,
                status = EXCLUDED.status,
                current_step = EXCLUDED.current_step,
                summary = EXCLUDED.summary,
                state_json = EXCLUDED.state_json,
                updated_at = NOW(),
                resumed_at = CASE
                    WHEN EXCLUDED.status = 'running'
                         AND tony_workflow_state.status IN ('paused', 'awaiting_approval')
                    THEN NOW()
                    ELSE tony_workflow_state.resumed_at
                END,
                completed_at = CASE
                    WHEN EXCLUDED.status IN ('completed', 'failed', 'cancelled')
                    THEN NOW()
                    ELSE tony_workflow_state.completed_at
                END
        """, (
            workflow_id[:120],
            workflow_type[:80],
            status[:40],
            current_step[:120] if current_step else None,
            summary[:500] if summary else None,
            psycopg2.extras.Json(state or {}),
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[WORKFLOW_STATE] upsert failed: {e}")
        return False


def list_workflow_states(
    *,
    status: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """List recent workflow states, optionally by status. Never raises."""
    init_workflow_state_table()
    try:
        bounded_limit = max(1, min(int(limit), 50))
    except Exception:
        bounded_limit = 20
    try:
        conn = get_conn()
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT workflow_id, workflow_type, status, current_step, summary,
                       state_json, created_at, updated_at, resumed_at, completed_at
                FROM tony_workflow_state
                WHERE status = %s
                ORDER BY updated_at DESC
                LIMIT %s
            """, (status, bounded_limit))
        else:
            cur.execute("""
                SELECT workflow_id, workflow_type, status, current_step, summary,
                       state_json, created_at, updated_at, resumed_at, completed_at
                FROM tony_workflow_state
                ORDER BY updated_at DESC
                LIMIT %s
            """, (bounded_limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_row_to_workflow(row) for row in rows]
    except Exception as e:
        print(f"[WORKFLOW_STATE] list failed: {e}")
        return []


def list_paused_workflows(limit: int = 20) -> List[Dict[str, Any]]:
    """Return workflows waiting for a resume/approval decision."""
    workflows = []
    for state in ("paused", "awaiting_approval"):
        workflows.extend(list_workflow_states(status=state, limit=limit))
    return sorted(
        workflows,
        key=lambda item: str(item.get("updated_at") or ""),
        reverse=True,
    )[:limit]
