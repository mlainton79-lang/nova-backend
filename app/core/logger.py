"""
Request audit + distillation-harvest choke point.

Two concerns funnelled through one entry point so every Tony response is
captured automatically without per-call-site oversight risk:

1. `request_logs` — short-form audit trail (existing behaviour). Truncated
   to 500 chars per field, mirrors what was already in production.
2. `tony_training_pairs` — full-fidelity harvest for the distillation track
   (Brick 1, 2026-05-31). Captures the un-truncated input, full system
   prompt context, full reply, and the conversation history that the model
   actually saw. Failures here are swallowed inside log_training_pair
   itself — the response path must never block on logging.

The 500-char truncation now happens INSIDE log_request (not at every call
site as before), so call sites should pass full `reply` text. Training
corpus gets the full content; request_logs gets the truncated audit form.
"""
import os
import psycopg2
from typing import Any, List, Optional, Union


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_log_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id SERIAL PRIMARY KEY,
                provider TEXT,
                message TEXT,
                reply TEXT,
                latency_ms INTEGER,
                ok BOOLEAN,
                error TEXT,
                deciding_brain TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LOGGER] init failed: {e}")


def log_request(
    provider,
    message,
    reply="",
    latency_ms=None,
    ok=True,
    error=None,
    deciding_brain=None,
    full_context: Optional[str] = None,
    task_type: Optional[str] = None,
    history: Optional[Union[List, Any]] = None,
    metadata: Optional[dict] = None,
):
    """Log a single user-Tony interaction.

    Writes to TWO tables in sequence:
    1. `request_logs` — truncated audit row (legacy behaviour preserved).
       Truncation now happens HERE rather than at call sites, so call
       sites can pass full reply text.
    2. `tony_training_pairs` — full-fidelity training-corpus row via
       log_training_pair(). Failure is swallowed inside that helper.

    Both writes are wrapped in try/except. log_request itself must never
    raise — response paths depend on it.

    New kwargs (for the distillation harvest layer, Brick 1 2026-05-31):
    - full_context: the assembled system prompt at dispatch time (None at
      short-circuit sites where no system prompt was built).
    - task_type: tag for the dispatch path. Values in current use:
      'chat', 'chat_stream', 'council', 'command', 'guard',
      'pending_action', 'gap_detector', 'injection_blocked'.
    - history: conversation history (list of HistoryMessage / dicts).
      Serialised to JSONB inside log_training_pair.
    - metadata: optional per-call metadata dict (image_present,
      document_present, etc.). Serialised to JSONB.
    """
    # 1. Audit row (request_logs) — truncated, legacy schema preserved.
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO request_logs "
            "(provider, message, reply, latency_ms, ok, error, deciding_brain) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                provider,
                (message or "")[:500],
                (reply or "")[:500],
                latency_ms,
                ok,
                error,
                deciding_brain,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LOGGER] log failed: {e}")

    # 2. Training pair (tony_training_pairs) — full fidelity. Always attempted;
    #    log_training_pair handles its own failures internally. Belt-and-braces
    #    try around the import in case the module is missing during a rollback
    #    window. log_request itself must never raise.
    try:
        from app.core.training_pairs import log_training_pair
        log_training_pair(
            user_input=message or "",
            model_answer=reply or "",
            source_model=(deciding_brain or provider or "unknown"),
            full_context=full_context,
            history=history,
            task_type=task_type,
            latency_ms=latency_ms,
            ok=ok,
            error=error,
            metadata=metadata,
        )
    except Exception as e:
        print(f"[LOGGER] training pair log failed: {e}")
