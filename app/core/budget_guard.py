"""
Budget Guard — hard caps on Tony's API spend.

Prevents runaway scenarios like:
  - Infinite loop in autonomous_loop generating capabilities forever
  - Failed retry logic hammering Gemini/Claude until credits drain
  - Buggy task that self-reschedules on every failure
  - Tony recursively triaging his own push notifications

Tracks API calls in a rolling window (hourly + daily). If thresholds are
breached, sets a freeze flag that every LLM-calling function checks before
firing. Matthew gets an alert. Tony stops autonomous work until reset.

Chat endpoints are NEVER blocked — Matthew can always talk to Tony.
Only background autonomous work is gated.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


# Default budget caps (conservative — one-user system)
DEFAULT_HOURLY_CALLS = 500      # max LLM calls per hour
DEFAULT_DAILY_CALLS = 5000      # max LLM calls per day
DEFAULT_HOURLY_COST = 5.00      # £5/hour max
DEFAULT_DAILY_COST = 30.00      # £30/day max


# Approximate costs per 1K tokens (rough, for rate-limit heuristic only)
COST_PER_1K = {
    "gemini-2.5-flash": 0.0003,
    "gemini-2.0-flash": 0.0002,
    "claude-sonnet-4-6": 0.015,
    "claude-opus": 0.075,
    "gpt-4o": 0.01,
    "gpt-4o-mini": 0.0005,
    "groq": 0.00005,
    "mistral": 0.002,
    "deepseek": 0.0001,
    "openrouter": 0.002,
    "xai": 0.005,
}


def init_budget_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_api_calls (
                id BIGSERIAL PRIMARY KEY,
                provider TEXT,
                operation TEXT,
                estimated_cost NUMERIC(10, 6) DEFAULT 0,
                estimated_tokens INT DEFAULT 0,
                source TEXT,
                called_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_calls_time
            ON tony_api_calls(called_at DESC)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_budget_state (
                id INT PRIMARY KEY DEFAULT 1,
                frozen BOOLEAN DEFAULT FALSE,
                freeze_reason TEXT,
                frozen_at TIMESTAMP,
                hourly_limit INT DEFAULT 500,
                daily_limit INT DEFAULT 5000,
                hourly_cost_limit NUMERIC(10,2) DEFAULT 5.00,
                daily_cost_limit NUMERIC(10,2) DEFAULT 30.00,
                CONSTRAINT only_one_row CHECK (id = 1)
            )
        """)
        # Ensure one row exists
        cur.execute("""
            INSERT INTO tony_budget_state (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """)
        cur.close()
        conn.close()
        print("[BUDGET] Tables initialised")
    except Exception as e:
        print(f"[BUDGET] Init failed: {e}")


def log_api_call(
    provider: str,
    operation: str = "chat",
    tokens: int = 0,
    source: str = "unknown",
):
    """Log an API call. Called from every LLM invocation."""
    try:
        # Estimate cost
        cost = 0.0
        for pattern, rate in COST_PER_1K.items():
            if pattern in provider.lower():
                cost = (tokens / 1000.0) * rate
                break

        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_api_calls
                (provider, operation, estimated_cost, estimated_tokens, source)
            VALUES (%s, %s, %s, %s, %s)
        """, (provider[:50], operation[:50], cost, tokens, source[:100]))
        cur.close()
        conn.close()
    except Exception:
        pass  # never block on budget logging


def get_usage(window_hours: int = 1) -> Dict:
    """Get usage stats for a given window."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*), COALESCE(SUM(estimated_cost), 0),
                   COALESCE(SUM(estimated_tokens), 0)
            FROM tony_api_calls
            WHERE called_at > NOW() - INTERVAL '{int(window_hours)} hours'
        """)
        count, cost, tokens = cur.fetchone()
        cur.close()
        conn.close()
        return {
            "window_hours": window_hours,
            "calls": count,
            "estimated_cost": float(cost),
            "tokens": tokens,
        }
    except Exception:
        return {"window_hours": window_hours, "calls": 0,
                "estimated_cost": 0.0, "tokens": 0}


def get_budget_state() -> Dict:
    """Check if budget is currently frozen."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT frozen, freeze_reason, frozen_at,
                   hourly_limit, daily_limit,
                   hourly_cost_limit, daily_cost_limit
            FROM tony_budget_state WHERE id = 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {"frozen": False}
        return {
            "frozen": row[0],
            "freeze_reason": row[1],
            "frozen_at": str(row[2]) if row[2] else None,
            "hourly_limit": row[3],
            "daily_limit": row[4],
            "hourly_cost_limit": float(row[5]) if row[5] else 0.0,
            "daily_cost_limit": float(row[6]) if row[6] else 0.0,
        }
    except Exception:
        return {"frozen": False}


def check_budget_and_freeze_if_needed() -> Dict:
    """
    Look at usage and freeze if limits exceeded.
    Returns current state.
    """
    state = get_budget_state()
    if state.get("frozen"):
        return state  # already frozen

    hourly = get_usage(1)
    daily = get_usage(24)

    reasons = []
    if hourly["calls"] > state.get("hourly_limit", DEFAULT_HOURLY_CALLS):
        reasons.append(f"hourly call limit exceeded ({hourly['calls']})")
    if daily["calls"] > state.get("daily_limit", DEFAULT_DAILY_CALLS):
        reasons.append(f"daily call limit exceeded ({daily['calls']})")
    if hourly["estimated_cost"] > state.get("hourly_cost_limit", DEFAULT_HOURLY_COST):
        reasons.append(f"hourly cost £{hourly['estimated_cost']:.2f} exceeded")
    if daily["estimated_cost"] > state.get("daily_cost_limit", DEFAULT_DAILY_COST):
        reasons.append(f"daily cost £{daily['estimated_cost']:.2f} exceeded")

    if reasons:
        reason = "; ".join(reasons)
        _freeze_autonomous_work(reason)
        return {"frozen": True, "freeze_reason": reason,
                "hourly": hourly, "daily": daily}

    return {"frozen": False, "hourly": hourly, "daily": daily}


def _freeze_autonomous_work(reason: str):
    """Set the frozen flag."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_budget_state
            SET frozen = TRUE, freeze_reason = %s, frozen_at = NOW()
            WHERE id = 1
        """, (reason[:500],))
        cur.close()
        conn.close()

        # Alert Matthew
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="budget_freeze",
                title="Tony's autonomous work frozen",
                body=f"Budget cap hit: {reason}. Chat still works. Reset with /budget/unfreeze when ready.",
                priority="high",
                source="budget_guard",
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[BUDGET] Freeze failed: {e}")


def unfreeze() -> Dict:
    """Manually unfreeze Tony's autonomous work."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_budget_state
            SET frozen = FALSE, freeze_reason = NULL, frozen_at = NULL
            WHERE id = 1
        """)
        cur.close()
        conn.close()
        return {"ok": True, "note": "Autonomous work unfrozen"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def is_autonomous_allowed() -> bool:
    """
    Gate for autonomous work. Any background task (not user chat) should
    call this before making LLM calls.

    Returns False if frozen. True otherwise.
    """
    state = get_budget_state()
    return not state.get("frozen", False)
