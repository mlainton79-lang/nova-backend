"""
Pending Action Router — short-lived state for multi-turn operator workflows.

Used when Tony asks the user a follow-up question and needs to remember
what was being asked. Examples:
  - email draft candidate selection
  - Vinted category disambiguation (future)
  - Calendar event disambiguation (future)
  - Approval confirmations (future)

Records expire automatically (default 5 min). On user reply that resolves
the action, the record is consumed (status=consumed) and the workflow
continues.
"""
import os
import json
import re
import psycopg2
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any

PENDING_ACTION_TTL_MINUTES = 5


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_pending_actions_table():
    """Idempotent table init. Called lazily before each store/fetch."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_pending_actions (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                session_key TEXT,
                original_query TEXT,
                instruction TEXT,
                candidates_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_actions_active
            ON tony_pending_actions (action_type, status, expires_at)
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[PENDING_ACTIONS] init failed: {e}")


def create_pending_action(
    action_type: str,
    original_query: str,
    candidates: List[Dict[str, Any]],
    instruction: Optional[str] = None,
    session_key: str = "default",
    ttl_minutes: int = PENDING_ACTION_TTL_MINUTES,
) -> Optional[int]:
    """Store a pending action, return its id."""
    init_pending_actions_table()
    try:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_pending_actions
            (action_type, session_key, original_query, instruction, candidates_json, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (action_type, session_key, original_query, instruction, json.dumps(candidates), expires_at))
        action_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return action_id
    except Exception as e:
        print(f"[PENDING_ACTIONS] create failed: {e}")
        return None


def get_active_pending_action(
    session_key: str = "default",
    action_type: Optional[str] = None,
) -> Optional[Dict]:
    """
    Return the most recent active pending action for this session/type, or None.
    Auto-marks expired records as 'expired' as a side effect (cheap cleanup).
    """
    init_pending_actions_table()
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Mark expired
        cur.execute("""
            UPDATE tony_pending_actions
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at < NOW()
        """)
        # Fetch active
        if action_type:
            cur.execute("""
                SELECT id, action_type, original_query, instruction, candidates_json, created_at, expires_at
                FROM tony_pending_actions
                WHERE session_key = %s AND action_type = %s AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
            """, (session_key, action_type))
        else:
            cur.execute("""
                SELECT id, action_type, original_query, instruction, candidates_json, created_at, expires_at
                FROM tony_pending_actions
                WHERE session_key = %s AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
            """, (session_key,))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "action_type": row[1],
            "original_query": row[2],
            "instruction": row[3],
            "candidates": json.loads(row[4]) if row[4] else [],
            "created_at": row[5],
            "expires_at": row[6],
        }
    except Exception as e:
        print(f"[PENDING_ACTIONS] get_active failed: {e}")
        return None


def consume_pending_action(action_id: int) -> bool:
    """Mark a pending action as consumed (resolved) so it won't fire again."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_pending_actions
            SET status = 'consumed'
            WHERE id = %s
        """, (action_id,))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[PENDING_ACTIONS] consume failed: {e}")
        return False


def parse_selection(message: str, max_candidates: int) -> Optional[int]:
    """
    Parse a user message as a selection number.
    Returns 1-indexed selection or None if not a clear selection.

    Accepts: "3", "3.", "number 3", "#3", "the third one", "option 3", "3rd"
    Rejects: anything else (lets it fall through to chat).
    """
    msg = (message or "").strip().lower()
    if not msg:
        return None

    # Bare number — "3", "3.", "#3"
    m = re.match(r'^#?(\d+)\.?$', msg)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= max_candidates else None

    # "number 3", "option 3", "choice 3", "pick 3"
    m = re.match(r'^(?:number|option|choice|pick)\s*#?(\d+)\.?$', msg)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= max_candidates else None

    # Word ordinals
    ordinals = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    }
    for word, n in ordinals.items():
        if re.match(rf'^(?:the\s+)?{word}(?:\s+one)?\.?$', msg):
            return n if 1 <= n <= max_candidates else None

    return None
