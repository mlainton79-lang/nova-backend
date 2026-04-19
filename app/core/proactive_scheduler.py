"""
Tony's Proactive Scheduler.

Tony monitors Matthew's calendar and time to surface the right
information at the right moment.

Examples:
- It's 19:00 and Matthew has a shift at 20:00 — Tony checks in
- Amelia has school tomorrow — Tony reminds about packed lunch
- It's payday week — Tony checks finances are in order
- Western Circle deadline approaching — Tony flags it
- Matthew hasn't messaged in 48h — Tony checks if something's wrong
- Weekend approaching — Tony suggests what to list on Vinted

Tony doesn't spam. He surfaces things when they actually matter.
"""
import os
import psycopg2
from datetime import datetime, timedelta, date
from typing import List, Dict
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def check_calendar_for_today() -> List[Dict]:
    """Pull today's calendar events and flag anything Tony should act on."""
    alerts = []
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Get events from Samsung calendar sync
        cur.execute("""
            SELECT title, start_time, end_time, description
            FROM samsung_calendar_events
            WHERE DATE(start_time) = CURRENT_DATE
               OR DATE(start_time) = CURRENT_DATE + INTERVAL '1 day'
            ORDER BY start_time ASC
            LIMIT 10
        """)
        events = cur.fetchall()
        cur.close()
        conn.close()

        now = datetime.utcnow()
        for title, start, end, desc in events:
            if start:
                hours_until = (start - now).total_seconds() / 3600
                if 0 < hours_until <= 2:
                    alerts.append({
                        "type": "imminent_event",
                        "title": f"Starting in {int(hours_until * 60)} mins: {title}",
                        "priority": "high"
                    })
                elif 2 < hours_until <= 24:
                    alerts.append({
                        "type": "upcoming_event",
                        "title": f"Tomorrow: {title}",
                        "priority": "normal"
                    })
    except Exception as e:
        print(f"[PROACTIVE_SCHED] Calendar check failed: {e}")
    return alerts


async def check_shift_patterns() -> List[Dict]:
    """
    Tony knows Matthew works nights at Sid Bailey.
    Check if a shift is likely tonight and prepare accordingly.
    """
    alerts = []
    now = datetime.utcnow()
    # UK time is UTC+1 (BST) in April
    uk_hour = (now.hour + 1) % 24
    uk_weekday = now.weekday()

    # Night shift prep window: 17:00-19:30 UK time
    if 17 <= uk_hour <= 19:
        alerts.append({
            "type": "shift_prep",
            "message": "Shift likely starting soon. Anything to sort before you head in?",
            "priority": "normal"
        })

    # Post-shift check: 08:00-10:00 UK (after 08:00 finish)
    if 8 <= uk_hour <= 10:
        alerts.append({
            "type": "post_shift",
            "message": "Just off a shift? Get some rest. Tony's been working while you slept.",
            "priority": "low"
        })

    return alerts


async def check_selling_opportunities() -> List[Dict]:
    """
    Tony monitors optimal selling windows.
    Weekend evenings are best for Vinted/eBay listings.
    """
    alerts = []
    now = datetime.utcnow()
    uk_hour = (now.hour + 1) % 24
    uk_weekday = now.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun

    # Friday/Saturday evening — prime listing time
    if uk_weekday in (4, 5) and 18 <= uk_hour <= 21:
        alerts.append({
            "type": "selling_window",
            "message": "Good time to list on Vinted/eBay — weekend shoppers are active now.",
            "priority": "low"
        })

    # Sunday evening — second best window
    if uk_weekday == 6 and 17 <= uk_hour <= 20:
        alerts.append({
            "type": "selling_window",
            "message": "Sunday evening — solid time to photograph items and create listings.",
            "priority": "low"
        })

    return alerts


async def run_proactive_scheduling() -> List[Dict]:
    """Full proactive scheduling run."""
    all_alerts = []

    for check_fn in [
        check_calendar_for_today,
        check_shift_patterns,
        check_selling_opportunities,
    ]:
        try:
            alerts = await check_fn()
            all_alerts.extend(alerts)
        except Exception as e:
            print(f"[PROACTIVE_SCHED] Check failed: {e}")

    # Create DB alerts for high-priority ones
    for alert in all_alerts:
        if alert.get("priority") in ("high", "urgent"):
            try:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type=alert.get("type", "schedule"),
                    title=alert.get("title", alert.get("message", ""))[:100],
                    body=alert.get("message", "")[:300],
                    priority=alert.get("priority", "normal"),
                    source="proactive_scheduler"
                )
            except Exception:
                pass

    if all_alerts:
        print(f"[PROACTIVE_SCHED] Generated {len(all_alerts)} scheduling alerts")

    return all_alerts
