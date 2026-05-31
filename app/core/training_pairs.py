"""
training_pairs.py — Brick 1 (HARVEST) of Nova's distillation track.

Captures every user-Tony interaction (input + system_prompt + history +
model answer + which model produced it) so a future brick can fine-tune
a Nova-owned small model and reduce dependence on frontier-model APIs.

Foundational contract:
- MUST NEVER raise from log_training_pair(). Failures are swallowed,
  the response path is never blocked. Missing rows in the harvest
  table are acceptable; a 500 to the user is not.
- Uses app.core.secrets_redact.redact() defensively on user_input,
  full_context, model_answer, error before insert. Even though
  upstream prompt assembly shouldn't embed API keys, defence in depth
  matches existing project practice (chat.py, all provider adapters).
- DB pattern follows AGENTS.md exactly: connect_timeout=10,
  conn.autocommit = True, with cur, try/finally close.
"""
import os
import json
import psycopg2
from typing import Any, Dict, List, Optional, Union

from app.core.secrets_redact import redact


def _connect():
    """Single source of connection shape per AGENTS.md."""
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def init_training_pairs_table() -> None:
    """Idempotent table init. Registered in app/api/v1/router.py _inits.

    Schema mirrors db/migrations/20260531120000_create_training_pairs.sql.
    Init failure is printed and non-fatal — first writes will then print
    log-failure messages until the underlying issue is fixed, but the
    response path keeps running.
    """
    conn = None
    try:
        conn = _connect()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tony_training_pairs (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    user_input TEXT NOT NULL,
                    full_context TEXT,
                    history_json JSONB,
                    model_answer TEXT,
                    source_model TEXT,
                    quality_flag TEXT,
                    task_type TEXT,
                    latency_ms INTEGER,
                    ok BOOLEAN DEFAULT TRUE,
                    error TEXT,
                    metadata_json JSONB DEFAULT '{}'::jsonb,
                    data_classification TEXT DEFAULT 'private'
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ttp_source_model "
                "ON tony_training_pairs(source_model)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ttp_task_type "
                "ON tony_training_pairs(task_type)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ttp_created_at "
                "ON tony_training_pairs(created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ttp_quality "
                "ON tony_training_pairs(quality_flag) "
                "WHERE quality_flag IS NOT NULL"
            )
        print("[TRAINING_PAIRS] Tables initialised")
    except Exception as e:
        # Non-fatal per AGENTS.md startup-init pattern.
        print(f"[TRAINING_PAIRS] Init failed: {e}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _history_to_jsonb(history: Optional[Union[List, Any]]) -> Optional[str]:
    """Serialise a list of conversation-history items to a JSON string the
    JSONB column can accept. Handles both Pydantic HistoryMessage objects
    and bare dicts (defensive — same shape council.py:_recent_context handles).
    Returns None on empty/None input or any conversion error.
    """
    if not history:
        return None
    try:
        items = []
        for h in history:
            role = getattr(h, "role", None)
            content = getattr(h, "content", None)
            if isinstance(h, dict):
                role = h.get("role", role)
                content = h.get("content", content)
            if role is None and content is None:
                continue
            items.append({"role": role or "unknown", "content": content or ""})
        return json.dumps(items) if items else None
    except Exception:
        return None


def log_training_pair(
    user_input: str,
    model_answer: str,
    source_model: str,
    full_context: Optional[str] = None,
    history: Optional[Union[List, Any]] = None,
    task_type: Optional[str] = None,
    latency_ms: Optional[int] = None,
    ok: bool = True,
    error: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> None:
    """Persist one user-Tony interaction as a candidate training pair.

    MUST NEVER raise. The response path depends on this being unable to
    surface a 500 even when the DB is down, the redactor is broken, or
    the table doesn't exist yet.

    All free-text fields are run through redact() defensively before
    insert. Matthew's PII (address, family details, etc.) is NOT redacted
    — this is his own data being captured for his own model. Only API-key-
    shaped substrings are scrubbed, matching project-wide redact() usage.
    """
    conn = None
    try:
        # Defensive redaction on all free-text fields. Matches the pattern
        # used in chat.py and the provider adapters before persisting strings.
        ui = redact(user_input or "")
        fc = redact(full_context) if full_context else None
        ma = redact(model_answer or "")
        err = redact(error) if error else None

        hist_json = _history_to_jsonb(history)
        meta_json = json.dumps(metadata or {})

        conn = _connect()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tony_training_pairs
                    (user_input, full_context, history_json, model_answer,
                     source_model, task_type, latency_ms, ok, error,
                     metadata_json)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    ui, fc, hist_json, ma,
                    source_model, task_type, latency_ms, ok, err,
                    meta_json,
                ),
            )
    except Exception as e:
        # MUST NEVER raise. Print to stderr (won't reach user). Also try
        # record_run_event so the next auditor can find this without log
        # scraping — but if THAT also fails, swallow. No content from
        # message/reply in run_event metadata (defence-in-depth: keeps
        # PII out of the observability surface too).
        print(f"[TRAINING_PAIRS] log failed: {e}")
        try:
            from app.observability import record_run_event, EventSeverity
            record_run_event(
                event_type="training_pair_log_failed",
                severity=EventSeverity.WARNING,
                subsystem="training_pairs.log",
                message="training pair insert failed",
                error_class=type(e).__name__,
                error_message=str(e)[:300],
                metadata={"source_model": source_model, "task_type": task_type},
            )
        except Exception:
            pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
