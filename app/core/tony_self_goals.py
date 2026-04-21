"""
Tony's Self-Goals — Tony's own active objectives about improving himself.

Distinct from tony_goals (Matthew's goals). These are Tony's intrinsic
motivations: improve memory retention rate, reduce fabrication incidents,
learn more about Matthew's family, improve briefing relevance.

Tony sets these himself from patterns in:
  - Eval failure categories (where he keeps regressing)
  - Fabrication detector frequency (where he invents stuff)
  - Diary followups (conversations he promised himself to revisit)
  - Self-improvement proposals (things he's asked to fix)

Once set, the goals become part of his prompt context so he actively works
toward them in subsequent conversations. Tracked with progress measurements.
"""
import os
import json
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_self_goals_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_self_goals (
                id SERIAL PRIMARY KEY,
                title TEXT,
                description TEXT,
                category TEXT,
                target_metric TEXT,
                target_value NUMERIC,
                current_value NUMERIC DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                completed_at TIMESTAMP
            )
        """)
        cur.close()
        conn.close()
        print("[SELF_GOALS] Tables initialised")
    except Exception as e:
        print(f"[SELF_GOALS] Init failed: {e}")


# Standing self-goals — Tony always has these
STANDING_GOALS = [
    {
        "title": "Keep fabrication rate at zero",
        "description": "Never invent specifics (brands, prices, sizes, dates) that Matthew hasn't provided. Target: 0 fabrications flagged per week.",
        "category": "accuracy",
        "target_metric": "fabrications_per_week",
        "target_value": 0,
    },
    {
        "title": "Pass all critical evals",
        "description": "Voice, CCJ isolation, honesty, fabrication, grief categories must all pass. Target: 100% critical pass rate.",
        "category": "quality",
        "target_metric": "critical_pass_rate",
        "target_value": 1.0,
    },
    {
        "title": "Build fact store over time",
        "description": "Extract at least 3 new facts per week from conversations.",
        "category": "memory",
        "target_metric": "new_facts_per_week",
        "target_value": 3,
    },
    {
        "title": "Respond to urgent emails within 30 minutes",
        "description": "Email monitor polls every 30 min. Urgent emails should trigger an alert within that window.",
        "category": "responsiveness",
        "target_metric": "urgent_email_response_time_min",
        "target_value": 30,
    },
    {
        "title": "Keep briefings short and relevant",
        "description": "Morning/evening briefings should be 2-4 sentences, naming specific priorities. Not a data dump.",
        "category": "voice",
        "target_metric": "avg_briefing_words",
        "target_value": 60,  # target max
    },
]


def ensure_standing_goals():
    """Make sure the standing goals exist. Idempotent."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for g in STANDING_GOALS:
            cur.execute("""
                INSERT INTO tony_self_goals
                    (title, description, category, target_metric, target_value, status)
                SELECT %s, %s, %s, %s, %s, 'active'
                WHERE NOT EXISTS (
                    SELECT 1 FROM tony_self_goals WHERE title = %s
                )
            """, (g["title"], g["description"], g["category"],
                  g["target_metric"], g["target_value"], g["title"]))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SELF_GOALS] ensure_standing failed: {e}")


def measure_progress() -> Dict[str, float]:
    """Calculate current values for each goal's metric."""
    progress = {}

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Fabrications per week
        try:
            cur.execute("""
                SELECT COUNT(*) FROM tony_suspected_fabrications
                WHERE created_at > NOW() - INTERVAL '7 days'
            """)
            progress["fabrications_per_week"] = cur.fetchone()[0]
        except Exception:
            progress["fabrications_per_week"] = None

        # New facts per week
        try:
            cur.execute("""
                SELECT COUNT(*) FROM tony_facts
                WHERE created_at > NOW() - INTERVAL '7 days'
                  AND superseded_by IS NULL
            """)
            progress["new_facts_per_week"] = cur.fetchone()[0]
        except Exception:
            progress["new_facts_per_week"] = None

        # Latest eval pass rate
        try:
            cur.execute("""
                SELECT pass_rate FROM tony_eval_runs
                ORDER BY run_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                progress["critical_pass_rate"] = float(row[0])
        except Exception:
            progress["critical_pass_rate"] = None

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SELF_GOALS] measure_progress failed: {e}")

    return progress


def update_goal_progress():
    """Update current_value on each goal based on measurements."""
    try:
        progress = measure_progress()
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for metric, value in progress.items():
            if value is None:
                continue
            cur.execute("""
                UPDATE tony_self_goals
                SET current_value = %s, updated_at = NOW()
                WHERE target_metric = %s AND status = 'active'
            """, (value, metric))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[SELF_GOALS] update_progress failed: {e}")


def list_active_goals() -> List[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, description, category,
                   target_metric, target_value, current_value,
                   status, created_at, updated_at
            FROM tony_self_goals
            WHERE status = 'active'
            ORDER BY
              CASE category
                WHEN 'accuracy' THEN 1
                WHEN 'quality' THEN 2
                WHEN 'memory' THEN 3
                ELSE 4
              END
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "title": r[1], "description": r[2],
             "category": r[3], "metric": r[4],
             "target": float(r[5]) if r[5] else None,
             "current": float(r[6]) if r[6] else 0,
             "status": r[7], "updated_at": str(r[9])}
            for r in rows
        ]
    except Exception:
        return []


def format_goals_for_prompt() -> str:
    """Inject active self-goals into Tony's prompt so he's aware of them."""
    goals = list_active_goals()
    if not goals:
        return ""

    lines = ["[TONY'S OWN ACTIVE OBJECTIVES — things I'm working on]"]
    for g in goals:
        lines.append(f"  • {g['title']}")
        if g.get("target") is not None and g.get("current") is not None:
            # For 'max' targets (fabrication, words) — good if current <= target
            # For 'min' targets (facts, pass_rate) — good if current >= target
            lines.append(f"    Current: {g['current']:.1f}  Target: {g['target']:.1f}")
    return "\n".join(lines)
