"""
Outcome Tracker — measures whether Tony's responses actually help Matthew.

Current AI builds hype by generating outputs. 'Reliability over hype' means
measuring if those outputs landed.

Three signals we can detect automatically:
  1. IMMEDIATE SATISFACTION: Next message is either silence (good), a 
     natural follow-up topic (good), or corrective ('no that's wrong',
     'actually I meant', 'try again').
  2. CLARIFICATION LOOP: Matthew's next message is essentially restating
     or clarifying the same question. Tony missed.
  3. PROVIDER SWITCH: Matthew immediately retries the same question on a
     different model. Strong dissatisfaction signal.
  4. ABANDONMENT: No response within 10 min, new unrelated topic. Low signal
     but worth tracking over time.

Every turn gets a score 0-1. Rolling average by week feeds Tony's self-goals
('Keep user satisfaction above 0.8'). Bad-streak triggers a diary note.
"""
import os
import re
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_outcome_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_outcomes (
                id SERIAL PRIMARY KEY,
                message_id TEXT,
                user_message TEXT,
                assistant_reply TEXT,
                provider TEXT,
                score NUMERIC(3, 2),
                signal TEXT,
                next_user_message TEXT,
                next_message_delay_seconds INT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_outcomes_time
            ON tony_outcomes(created_at DESC)
        """)
        cur.close()
        conn.close()
        print("[OUTCOMES] Tables initialised")
    except Exception as e:
        print(f"[OUTCOMES] Init failed: {e}")


# Signals in Matthew's follow-up message that indicate Tony missed
CORRECTIVE_PATTERNS = [
    r"\b(no|nope|that's not|that isn't|that wasn't|that's wrong|not quite)\b",
    r"\b(actually|i meant|i was asking|what i said was)\b",
    r"\b(try again|redo|do it again|start over|again\??)\b",
    r"\b(you('re| are) wrong|you('ve| have) got|misunderstood)\b",
    r"\b(that doesn'?t|that isn'?t|doesn'?t make sense)\b",
]

CLARIFICATION_PATTERNS = [
    r"^\?\s*$",
    r"\b(what do you mean|what does that mean|can you clarify|i don'?t follow)\b",
    r"\b(explain|elaborate|more detail|go deeper)\b",
    r"^huh\??$",
    r"^eh\??$",
]


def _classify_followup(user_reply: str) -> str:
    """Classify Matthew's follow-up message relative to Tony's previous reply."""
    if not user_reply:
        return "no_reply"

    r = user_reply.lower().strip()

    # Very short acknowledgements — often good or neutral
    if r in ("ok", "okay", "alright", "cheers", "thanks", "ta", "yeah", "yep", "sound"):
        return "acknowledgement"

    # Corrections
    for pat in CORRECTIVE_PATTERNS:
        if re.search(pat, r):
            return "corrective"

    # Clarification requests
    for pat in CLARIFICATION_PATTERNS:
        if re.search(pat, r):
            return "clarification"

    # Abrupt switch
    if r.startswith(("anyway", "change of subject", "different question", "new topic")):
        return "topic_switch"

    # Anything else — assume continuing a working dialogue
    return "continuation"


def _score_signal(signal: str, delay_seconds: Optional[int]) -> float:
    """Convert a signal into a 0-1 satisfaction score."""
    # Higher is better
    scores = {
        "acknowledgement":   0.9,
        "continuation":      0.8,
        "topic_switch":      0.7,
        "no_reply":          0.6,   # ambiguous
        "clarification":     0.4,
        "corrective":        0.15,
    }
    base = scores.get(signal, 0.5)

    # Long delay (>30 min) with corrective = worse than immediate correction
    if delay_seconds is not None and delay_seconds > 1800 and signal == "corrective":
        base -= 0.1

    return max(0.0, min(1.0, base))


def record_outcome(
    message_id: str,
    user_message: str,
    assistant_reply: str,
    provider: str,
    next_user_message: Optional[str],
    delay_seconds: Optional[int],
) -> Dict:
    """
    Called when a new user message arrives (and there was a previous Tony reply).
    Retroactively scores the previous reply.
    """
    signal = _classify_followup(next_user_message or "")
    score = _score_signal(signal, delay_seconds)

    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_outcomes
                (message_id, user_message, assistant_reply, provider,
                 score, signal, next_user_message, next_message_delay_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            message_id[:100] if message_id else None,
            (user_message or "")[:1000],
            (assistant_reply or "")[:2000],
            (provider or "")[:50],
            score,
            signal,
            (next_user_message or "")[:500],
            delay_seconds,
        ))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[OUTCOMES] Record failed: {e}")

    return {"score": score, "signal": signal}


def get_rolling_satisfaction(days: int = 7) -> Dict:
    """Average satisfaction over last N days by provider + overall."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT
              AVG(score)::numeric(3,2) AS avg_score,
              COUNT(*) AS sample_size,
              COUNT(CASE WHEN signal = 'corrective' THEN 1 END) AS corrections,
              COUNT(CASE WHEN signal = 'clarification' THEN 1 END) AS clarifications
            FROM tony_outcomes
            WHERE created_at > NOW() - INTERVAL '{int(days)} days'
        """)
        row = cur.fetchone()
        overall = {
            "avg_score": float(row[0]) if row[0] else None,
            "sample_size": row[1],
            "corrections": row[2],
            "clarifications": row[3],
        }

        cur.execute(f"""
            SELECT provider, AVG(score)::numeric(3,2), COUNT(*)
            FROM tony_outcomes
            WHERE created_at > NOW() - INTERVAL '{int(days)} days'
            GROUP BY provider ORDER BY COUNT(*) DESC
        """)
        by_provider = {r[0]: {"avg_score": float(r[1]) if r[1] else None,
                               "count": r[2]} for r in cur.fetchall()}

        cur.close()
        conn.close()
        return {"days": days, "overall": overall, "by_provider": by_provider}
    except Exception as e:
        return {"error": str(e)}


def recent_bad_outcomes(limit: int = 10) -> List[Dict]:
    """Get recent corrective/clarification outcomes for review."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_message, assistant_reply, next_user_message,
                   signal, score, created_at
            FROM tony_outcomes
            WHERE signal IN ('corrective', 'clarification')
              AND created_at > NOW() - INTERVAL '14 days'
            ORDER BY score ASC, created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "user_message": r[1][:200],
             "assistant_reply": r[2][:300], "next_user_message": r[3][:200],
             "signal": r[4], "score": float(r[5]),
             "created_at": str(r[6])}
            for r in rows
        ]
    except Exception:
        return []
