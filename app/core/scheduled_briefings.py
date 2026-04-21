"""
Scheduled briefings — auto-deliver intelligent briefings at key moments.

Uses the task queue to schedule:
  - Pre-shift brief at 18:30 on shift days ('2 hours before your shift')
  - Post-shift brief at 09:00 after overnight shift ('you're home now')  
  - Mid-morning brief at 09:00 on days off
  - Evening prep at 20:00 on days off

The brief gets delivered as a high-priority alert (visible on next app open)
and a push notification (once FCM is configured).
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def deliver_scheduled_brief(task_id: int, payload: dict) -> dict:
    """
    Task handler: generates and posts an intelligent briefing.
    Called from the task queue at scheduled times.
    """
    try:
        from app.core.intelligent_briefing import get_intelligent_briefing
        from app.core.proactive import create_alert
        from app.core.task_queue import update_progress

        brief_type = payload.get("type", "scheduled")
        update_progress(task_id, f"Generating {brief_type} briefing", 10)

        result = await get_intelligent_briefing()
        brief_text = result.get("briefing", "Tony ready.")

        update_progress(task_id, "Posting as alert", 80)

        # Type-specific titling
        titles = {
            "pre_shift":  "Before your shift",
            "post_shift": "Home from shift",
            "morning":    "Morning briefing",
            "evening":    "Evening check-in",
        }
        title = titles.get(brief_type, "Tony brief")

        create_alert(
            alert_type="scheduled_brief",
            title=title,
            body=brief_text[:500],
            priority="normal",  # avoid the push recursion loop
            source="scheduled_briefing",
        )

        update_progress(task_id, "Delivered", 100)
        return {"ok": True, "type": brief_type, "chars": len(brief_text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _seconds_until(target_hour: int, target_min: int = 0) -> int:
    """Seconds from now until the next occurrence of HH:MM (local/UTC rough)."""
    now = datetime.utcnow()
    target = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds())


def schedule_todays_briefs() -> list:
    """
    Work out today's briefings based on shift status + time of day.
    Queue them with appropriate delays.
    """
    try:
        from app.core.task_queue import queue_task
        from app.core.rota import get_shift_status

        scheduled = []
        # Use actual rota functions rather than a non-existent aggregate
        try:
            from app.core.rota import (
                is_currently_on_shift, next_shift_start, is_working_on_date
            )
            from datetime import date
            on_shift_now = is_currently_on_shift()
            next_start = next_shift_start()
            from datetime import datetime
            hours_to_next = None
            if next_start:
                hours_to_next = (next_start - datetime.utcnow()).total_seconds() / 3600
            is_shift_day = on_shift_now or (hours_to_next is not None and hours_to_next < 14)
        except Exception as e:
            print(f"[SCHEDULED_BRIEFS] Rota read failed: {e}")
            on_shift_now = False
            is_shift_day = False

        # Don't double-schedule — check if one already exists in the last 6h
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT task_type FROM tony_task_queue
            WHERE task_type = 'scheduled_brief'
              AND created_at > NOW() - INTERVAL '6 hours'
        """)
        already = bool(cur.fetchone())
        cur.close()
        conn.close()

        if already:
            return []

        if is_shift_day:
            # Pre-shift brief at 18:30 UTC (19:30 BST)
            delay_pre = _seconds_until(18, 30)
            if delay_pre < 86400:  # don't schedule more than a day ahead
                tid = queue_task("scheduled_brief", {"type": "pre_shift"}, delay_seconds=delay_pre)
                scheduled.append({"type": "pre_shift", "task_id": tid, "delay_s": delay_pre})
        else:
            # Day off — morning brief at 09:00
            delay_morn = _seconds_until(9)
            if delay_morn < 43200:  # only if within 12h
                tid = queue_task("scheduled_brief", {"type": "morning"}, delay_seconds=delay_morn)
                scheduled.append({"type": "morning", "task_id": tid, "delay_s": delay_morn})

        # Post-shift brief always available after overnight shift
        if shift.get("on_shift_now"):
            # 08:30 UTC next morning
            delay_post = _seconds_until(8, 30)
            tid = queue_task("scheduled_brief", {"type": "post_shift"}, delay_seconds=delay_post)
            scheduled.append({"type": "post_shift", "task_id": tid, "delay_s": delay_post})

        return scheduled
    except Exception as e:
        print(f"[SCHEDULED_BRIEFS] Schedule failed: {e}")
        return []


def register_brief_handler():
    """Register the deliver_scheduled_brief handler with the task queue."""
    try:
        from app.core.task_queue import register_handler
        register_handler("scheduled_brief", deliver_scheduled_brief)
        print("[SCHEDULED_BRIEFS] Handler registered")
    except Exception as e:
        print(f"[SCHEDULED_BRIEFS] Handler registration failed: {e}")
