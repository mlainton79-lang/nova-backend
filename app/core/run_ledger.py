"""
Run Ledger - backend module (R1.5).

The permanent, append-only record of every autonomous action Tony takes.
One row per action: what it was, what triggered it, when, the outcome,
and the trace ID that ties it back to the session that produced it.

Mirrors vinted_jobs.py / pending_actions.py shape: lazy idempotent table
init, simple helpers per operation, psycopg2 connection-per-call.

This is the audit spine. The Pending Action Router and Tony's executors
write into it; a future Tony Status screen reads from it. It is what makes
"Tony did things while Matthew slept" reviewable rather than a liability.

One table:
  tony_run_ledger  - append-only, one row per autonomous action

Status values:
  started            - action begun, not yet finished
  success            - completed successfully
  failed             - completed with an error
  awaiting_approval  - paused at the Pending Action Router human gate
"""
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_run_ledger_table():
    """Idempotent - called lazily before each operation."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_run_ledger (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                trigger TEXT,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'started',
                result TEXT,
                trace_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                metadata_json JSONB DEFAULT '{}'::jsonb
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_run_ledger_type_created
            ON tony_run_ledger (action_type, created_at DESC)
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[RUN_LEDGER] init failed: {e}")
