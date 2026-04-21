"""
Email monitor — runs periodically, triages new unread emails, creates alerts
for anything urgent. Keeps Matthew ahead of important messages without him
having to check.

Schedule: every 30 min via the task_queue. Idempotent — uses email hash to 
track what's been triaged, so re-runs only process genuinely new items.
"""
import os
import asyncio
from typing import Dict


async def handle_email_monitor_task(task_id: int, payload: Dict) -> Dict:
    """
    Task handler: pulls unread emails, triages any not yet seen, creates
    alerts for urgent items.
    """
    try:
        from app.core.task_queue import update_progress, queue_task
        from app.core.gmail_service import get_all_accounts, list_emails
        from app.core.email_triage import triage_emails, _hash_email, _get_cached_triage
        from app.core.proactive import create_alert

        update_progress(task_id, "Polling Gmail accounts", 10)

        accounts = get_all_accounts()
        if not accounts:
            _schedule_next()
            return {"ok": True, "note": "No accounts configured"}

        all_new = []
        for account in accounts:
            try:
                emails = await list_emails(
                    account, query="is:unread newer_than:1d",
                    max_results=10, label=""
                )
                # Filter to ones we haven't triaged yet
                new_emails = [e for e in emails if _get_cached_triage(_hash_email(e)) is None]
                all_new.extend(new_emails)
            except Exception as e:
                print(f"[EMAIL_MONITOR] {account} list failed: {e}")

        if not all_new:
            update_progress(task_id, "No new unread emails", 100)
            _schedule_next()
            return {"ok": True, "new_count": 0}

        update_progress(task_id, f"Triaging {len(all_new)} new email(s)", 30)

        triaged = await triage_emails(all_new, use_cache=False)

        # Alert on urgent
        urgent = [t for t in triaged if t["triage"]["urgency"] == "urgent"]
        for e in urgent:
            try:
                sender_name = (e.get("from", "") or "Unknown").split("<")[0].strip()
                create_alert(
                    alert_type="urgent_email",
                    title=f"Urgent email from {sender_name}",
                    body=e["triage"]["summary"][:300],
                    priority="high",
                    source="email_monitor",
                )
            except Exception as ex:
                print(f"[EMAIL_MONITOR] Alert failed: {ex}")

        update_progress(task_id,
            f"Done. {len(triaged)} triaged, {len(urgent)} urgent", 100)

        _schedule_next()

        return {
            "ok": True,
            "new_count": len(triaged),
            "urgent_count": len(urgent),
            "summary": {e["triage"]["urgency"]: e["triage"]["summary"] for e in urgent},
        }
    except Exception as e:
        print(f"[EMAIL_MONITOR] Task failed: {e}")
        _schedule_next()  # keep the loop alive even if this iteration failed
        return {"ok": False, "error": str(e)}


def _schedule_next(delay_minutes: int = 30):
    """Queue the next email monitor run."""
    try:
        from app.core.task_queue import queue_task
        # Check if one is already queued to avoid pileup
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM tony_task_queue
            WHERE task_type = 'email_monitor'
              AND status IN ('queued', 'claimed', 'running')
            LIMIT 1
        """)
        already = cur.fetchone()
        cur.close()
        conn.close()
        if already:
            return
        queue_task("email_monitor", {}, delay_seconds=delay_minutes * 60)
    except Exception as e:
        print(f"[EMAIL_MONITOR] Re-schedule failed: {e}")


def register_monitor():
    """Register handler and kick off first run."""
    try:
        from app.core.task_queue import register_handler, queue_task
        register_handler("email_monitor", handle_email_monitor_task)

        # Kick off first run in 2 minutes (give app time to fully boot)
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM tony_task_queue
            WHERE task_type = 'email_monitor'
              AND status IN ('queued', 'claimed', 'running')
            LIMIT 1
        """)
        already = cur.fetchone()
        cur.close()
        conn.close()
        if not already:
            queue_task("email_monitor", {}, delay_seconds=120)
            print("[EMAIL_MONITOR] First run queued in 2 min, every 30 min after")
        else:
            print("[EMAIL_MONITOR] Handler registered; existing task will run on schedule")
    except Exception as e:
        print(f"[EMAIL_MONITOR] Register failed: {e}")
