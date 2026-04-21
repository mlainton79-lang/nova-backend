"""
Tony's health dashboard. Single endpoint that returns a snapshot of everything
important: recent evals, active tasks, fact count, skills, build log, alerts.

Intended for quick sanity check from anywhere: 'is Tony healthy?'
"""
from fastapi import APIRouter, Depends
import os
import psycopg2
from app.core.security import verify_token

router = APIRouter()


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


@router.get("/health/dashboard")
async def health_dashboard(_=Depends(verify_token)):
    """One endpoint, everything important, isolated error handling per query."""
    out = {"ok": True, "checks": {}}

    def _query(name: str, fn):
        try:
            result = fn()
            out["checks"][name] = {"ok": True, "value": result}
        except Exception as e:
            out["checks"][name] = {"ok": False, "error": str(e)[:200]}

    conn = None
    try:
        conn = get_conn()
        conn.autocommit = True
    except Exception as e:
        out["ok"] = False
        out["error"] = f"DB connection failed: {e}"
        return out

    def _cur():
        return conn.cursor()

    # Recent evals
    def recent_evals():
        cur = _cur()
        cur.execute("""
            SELECT run_at, endpoint, passed, total, pass_rate
            FROM tony_eval_runs
            ORDER BY run_at DESC LIMIT 5
        """)
        return [
            {"run_at": str(r[0]), "endpoint": r[1], "passed": r[2],
             "total": r[3], "pass_rate": r[4]}
            for r in cur.fetchall()
        ]
    _query("recent_evals", recent_evals)

    # Active tasks
    def active_tasks():
        cur = _cur()
        cur.execute("""
            SELECT id, task_type, status, progress_msg, progress_pct
            FROM tony_task_queue
            WHERE status IN ('queued','running','claimed')
            ORDER BY created_at DESC LIMIT 10
        """)
        return [{"id": r[0], "type": r[1], "status": r[2],
                 "msg": r[3], "pct": r[4]} for r in cur.fetchall()]
    _query("active_tasks", active_tasks)

    # Fact count
    def fact_count():
        cur = _cur()
        cur.execute("SELECT COUNT(*) FROM tony_facts WHERE superseded_by IS NULL")
        return cur.fetchone()[0]
    _query("fact_count", fact_count)

    # Active skills
    def active_skills():
        cur = _cur()
        cur.execute("SELECT name, version FROM tony_skills ORDER BY name")
        return [{"name": r[0], "version": r[1]} for r in cur.fetchall()]
    _query("skills", active_skills)

    # Recent capability builds
    def recent_builds():
        cur = _cur()
        cur.execute("""
            SELECT capability_name, status, created_at
            FROM tony_capability_requests
            ORDER BY created_at DESC LIMIT 5
        """)
        return [{"name": r[0], "status": r[1], "created_at": str(r[2])}
                for r in cur.fetchall()]
    _query("recent_builds", recent_builds)

    # Unread alerts count (filtered)
    def alerts_summary():
        cur = _cur()
        cur.execute("""
            SELECT priority, COUNT(*) FROM tony_alerts
            WHERE read = FALSE
              AND source != 'tony_push'
              AND title NOT LIKE '%Tony — Urgent%'
              AND created_at > NOW() - INTERVAL '7 days'
            GROUP BY priority
        """)
        return {r[0]: r[1] for r in cur.fetchall()}
    _query("unread_alerts", alerts_summary)

    # Pending email triage
    def triage_summary():
        cur = _cur()
        cur.execute("""
            SELECT urgency, COUNT(*) FROM tony_email_triage
            WHERE triaged_at > NOW() - INTERVAL '3 days'
            GROUP BY urgency
        """)
        return {r[0]: r[1] for r in cur.fetchall()}
    _query("recent_triage", triage_summary)

    # Most recent commit
    def last_commit():
        try:
            import subprocess
            r = subprocess.run(
                ["git", "log", "-1", "--format=%h %s"],
                capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                timeout=3
            )
            return r.stdout.strip() if r.returncode == 0 else "unknown"
        except Exception:
            return "git not available"
    _query("last_commit", last_commit)

    try:
        conn.close()
    except Exception:
        pass

    return out
