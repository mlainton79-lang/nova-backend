"""
Tony's Task Queue.

Lets Tony run long-horizon tasks in the background without blocking
chat responses. Tasks persist across Railway restarts via Postgres.

A task is any async function that takes time:
  - Running web research across 20+ sources
  - Multi-step capability builds with iteration
  - Bulk email analysis
  - Background learning jobs
  - Scheduled reports

Typical flow:
  1. queue_task(name, payload) -> task_id, status='queued'
  2. Background worker picks it up, sets status='running'
  3. Worker updates progress messages as it runs
  4. On completion: status='done', result stored
  5. Tony checks status via get_task(task_id) or lists via list_tasks()
"""
import os
import json
import psycopg2
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Optional, Callable, Any


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


# In-process handler registry — maps task_type -> async function
_HANDLERS: Dict[str, Callable] = {}


def register_handler(task_type: str, handler: Callable):
    """Register an async function to handle tasks of a given type."""
    _HANDLERS[task_type] = handler


def init_task_queue_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_task_queue (
                id SERIAL PRIMARY KEY,
                task_type TEXT NOT NULL,
                payload JSONB,
                status TEXT DEFAULT 'queued',
                progress_msg TEXT,
                progress_pct INT DEFAULT 0,
                result JSONB,
                error TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                attempt INT DEFAULT 0,
                max_attempts INT DEFAULT 2,
                scheduled_for TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_queue_status
            ON tony_task_queue(status, scheduled_for)
        """)
        cur.close()
        conn.close()
        print("[TASK_QUEUE] Tables initialised")
    except Exception as e:
        print(f"[TASK_QUEUE] Init failed: {e}")


def queue_task(task_type: str, payload: Dict = None,
               delay_seconds: int = 0, max_attempts: int = 2) -> int:
    """Queue a task. Returns task_id or -1 on failure."""
    from datetime import timedelta
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        scheduled = datetime.utcnow() + timedelta(seconds=delay_seconds)
        cur.execute("""
            INSERT INTO tony_task_queue (task_type, payload, scheduled_for, max_attempts)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (task_type, json.dumps(payload or {}), scheduled, max_attempts))
        task_id = cur.fetchone()[0]
        cur.close()
        conn.close()
        print(f"[TASK_QUEUE] Queued {task_type} as task {task_id}")
        return task_id
    except Exception as e:
        print(f"[TASK_QUEUE] Queue failed: {e}")
        return -1


def update_progress(task_id: int, message: str, pct: int = None):
    """Worker calls this to update task progress."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        if pct is not None:
            cur.execute("""
                UPDATE tony_task_queue
                SET progress_msg = %s, progress_pct = %s
                WHERE id = %s
            """, (message[:500], pct, task_id))
        else:
            cur.execute("""
                UPDATE tony_task_queue
                SET progress_msg = %s
                WHERE id = %s
            """, (message[:500], task_id))
        cur.close()
        conn.close()
    except Exception:
        pass


def get_task(task_id: int) -> Optional[Dict]:
    """Fetch a single task's state."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, task_type, payload, status, progress_msg, progress_pct,
                   result, error, created_at, started_at, completed_at, attempt
            FROM tony_task_queue WHERE id = %s
        """, (task_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "task_type": row[1], "payload": row[2],
            "status": row[3], "progress_msg": row[4], "progress_pct": row[5],
            "result": row[6], "error": row[7],
            "created_at": str(row[8]) if row[8] else None,
            "started_at": str(row[9]) if row[9] else None,
            "completed_at": str(row[10]) if row[10] else None,
            "attempt": row[11],
        }
    except Exception as e:
        print(f"[TASK_QUEUE] get_task failed: {e}")
        return None


def list_active_tasks(limit: int = 20) -> list:
    """List running or recently-completed tasks."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, task_type, status, progress_msg, progress_pct, created_at
            FROM tony_task_queue
            WHERE status IN ('queued', 'running')
               OR completed_at > NOW() - INTERVAL '1 hour'
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "task_type": r[1], "status": r[2],
             "progress_msg": r[3], "progress_pct": r[4],
             "created_at": str(r[5])}
            for r in rows
        ]
    except Exception:
        return []


async def _execute_task(task_id: int, task_type: str, payload: Dict) -> Dict:
    """Run a single task through its registered handler."""
    handler = _HANDLERS.get(task_type)
    if handler is None:
        return {"ok": False, "error": f"No handler registered for {task_type!r}"}

    try:
        # Mark running
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_task_queue
            SET status = 'running', started_at = NOW(), attempt = attempt + 1
            WHERE id = %s
        """, (task_id,))
        cur.close()
        conn.close()

        # Run
        result = await handler(task_id, payload)

        # Mark done
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_task_queue
            SET status = 'done', completed_at = NOW(),
                result = %s, progress_pct = 100
            WHERE id = %s
        """, (json.dumps(result or {}), task_id))
        cur.close()
        conn.close()
        return {"ok": True, "result": result}

    except Exception as e:
        err_text = f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1000]}"
        try:
            conn = get_conn()
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("""
                UPDATE tony_task_queue
                SET status = 'failed', completed_at = NOW(), error = %s
                WHERE id = %s
            """, (err_text, task_id))
            cur.close()
            conn.close()
        except Exception:
            pass
        print(f"[TASK_QUEUE] Task {task_id} failed: {err_text[:500]}")
        return {"ok": False, "error": str(e)}


async def worker_loop(poll_interval_seconds: int = 10):
    """
    Background worker. Polls the queue and executes tasks in-process.
    Runs as an asyncio task alongside the FastAPI app.
    """
    print(f"[TASK_QUEUE] Worker loop started (poll every {poll_interval_seconds}s)")
    while True:
        try:
            conn = get_conn()
            conn.autocommit = True
            cur = conn.cursor()
            # Pick up next task, atomically
            cur.execute("""
                UPDATE tony_task_queue
                SET status = 'claimed'
                WHERE id = (
                    SELECT id FROM tony_task_queue
                    WHERE status = 'queued'
                      AND scheduled_for <= NOW()
                      AND attempt < max_attempts
                    ORDER BY scheduled_for ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, task_type, payload
            """)
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row:
                task_id, task_type, payload = row
                if isinstance(payload, str):
                    try: payload = json.loads(payload)
                    except Exception: payload = {}
                print(f"[TASK_QUEUE] Executing task {task_id} ({task_type})")
                # Run without blocking the polling loop — fire as task
                asyncio.create_task(_execute_task(task_id, task_type, payload or {}))
            else:
                await asyncio.sleep(poll_interval_seconds)
        except Exception as e:
            print(f"[TASK_QUEUE] Worker error: {e}")
            await asyncio.sleep(poll_interval_seconds)
