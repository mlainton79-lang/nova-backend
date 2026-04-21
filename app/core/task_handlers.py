"""
Registered task handlers for Tony's task queue.

Each handler is an async function that takes (task_id, payload) and returns
a result dict. Register them at startup so the worker can dispatch.
"""
import os
import asyncio
from typing import Dict
from datetime import datetime, timedelta

from app.core.task_queue import register_handler, update_progress, queue_task


async def handle_daily_eval_run(task_id: int, payload: Dict) -> Dict:
    """Runs the full eval suite against live Tony, logs results, alerts on failures."""
    try:
        update_progress(task_id, "Starting daily eval run", 0)
        from app.evals.runner import run_all, log_result_to_db

        update_progress(task_id, "Running tests against chat endpoint", 10)
        summary_chat = await run_all(endpoint="chat")
        log_result_to_db(summary_chat)

        update_progress(task_id, f"Chat: {summary_chat['passed']}/{summary_chat['total']} passed. Running council endpoint", 50)
        summary_council = await run_all(endpoint="council")
        log_result_to_db(summary_council)

        update_progress(task_id, "Evals complete. Checking for critical regressions", 90)

        # Alert if critical failures
        critical_cats = {"voice", "ccj_isolation", "honesty", "fabrication", "grief"}
        critical_failures = [
            r for r in summary_chat["results"] + summary_council["results"]
            if not r["passed"] and r.get("category") in critical_cats
        ]
        if critical_failures:
            from app.core.proactive import create_alert
            failing_ids = "; ".join(sorted({f["id"] for f in critical_failures})[:5])
            create_alert(
                alert_type="eval_regression",
                title=f"Daily eval: {len(critical_failures)} critical failures",
                body=f"Failing tests: {failing_ids}",
                priority="high",
                source="daily_evals",
                expires_hours=48,
            )

        # Run self-improvement analysis on any failures
        try:
            from app.core.self_improvement import analyse_eval_failures
            # Use the most recent run ID (we just logged two)
            import psycopg2
            conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
            cur = conn.cursor()
            cur.execute("SELECT id FROM tony_eval_runs ORDER BY run_at DESC LIMIT 2")
            run_ids = [r[0] for r in cur.fetchall()]
            cur.close()
            conn.close()
            total_proposals = 0
            for rid in run_ids:
                proposals = await analyse_eval_failures(rid)
                total_proposals += len(proposals)
            update_progress(task_id,
                f"Self-improvement: {total_proposals} proposals queued for review", 95)
        except Exception as e:
            print(f"[DAILY_EVAL] Self-improvement failed: {e}")

        update_progress(task_id, "Done", 100)
        return {
            "chat": {"passed": summary_chat["passed"], "total": summary_chat["total"],
                     "pass_rate": summary_chat["pass_rate"]},
            "council": {"passed": summary_council["passed"], "total": summary_council["total"],
                        "pass_rate": summary_council["pass_rate"]},
            "critical_failures": len(critical_failures),
        }
    except Exception as e:
        return {"error": str(e)}


async def handle_deep_research(task_id: int, payload: Dict) -> Dict:
    """
    Run extended web research on a topic. Can take 5-15 min.
    Payload: {"topic": "...", "angle": "...", "max_sources": 15}
    """
    topic = payload.get("topic", "")
    angle = payload.get("angle", "")
    max_sources = int(payload.get("max_sources", 10))
    if not topic:
        return {"error": "No topic supplied"}

    try:
        update_progress(task_id, f"Starting deep research: {topic}", 0)

        # Use existing research infrastructure if present
        try:
            from app.core.research import run_deep_research
            update_progress(task_id, "Running deep research module", 20)
            result = await run_deep_research(topic, angle=angle, max_sources=max_sources)
            update_progress(task_id, "Research complete, summarising findings", 90)
            return {"topic": topic, "findings": result}
        except ImportError:
            # Fall back to simpler Brave search + Gemini summary
            update_progress(task_id, "Using simple search fallback", 20)
            from app.core.router import brave_search
            hits = await brave_search(f"{topic} {angle}".strip(), max_results=max_sources)
            update_progress(task_id, f"Got {len(hits)} results. Summarising", 60)
            return {"topic": topic, "source_count": len(hits), "hits": hits[:max_sources]}
    except Exception as e:
        return {"error": str(e)}


async def handle_scheduled_reminder(task_id: int, payload: Dict) -> Dict:
    """
    Fire a proactive alert at a scheduled time.
    Payload: {"title": "...", "body": "...", "priority": "high"}
    """
    try:
        from app.core.proactive import create_alert
        title = payload.get("title", "Reminder")
        body = payload.get("body", "")
        priority = payload.get("priority", "normal")
        create_alert(alert_type="reminder", title=title, body=body,
                     priority=priority, source="scheduled_reminder",
                     expires_hours=72)
        return {"ok": True, "fired_at": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"error": str(e)}


def schedule_daily_evals():
    """Queue a daily eval task if one isn't already scheduled for today."""
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM tony_task_queue
            WHERE task_type = 'daily_eval_run'
              AND created_at > NOW() - INTERVAL '20 hours'
            LIMIT 1
        """)
        existing = cur.fetchone()
        cur.close()
        conn.close()
        if existing:
            return None
        # Queue for early AM when Tony is idle
        return queue_task("daily_eval_run", {}, delay_seconds=0)
    except Exception as e:
        print(f"[HANDLERS] schedule_daily_evals failed: {e}")
        return None


def register_all_handlers():
    """Call at startup to register all known task handlers."""
    register_handler("daily_eval_run", handle_daily_eval_run)
    register_handler("deep_research", handle_deep_research)
    register_handler("scheduled_reminder", handle_scheduled_reminder)
    print("[TASK_HANDLERS] Registered handlers: daily_eval_run, deep_research, scheduled_reminder")
