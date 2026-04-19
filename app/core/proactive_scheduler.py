"""
Tony's Proactive Scheduling Intelligence.

Tony doesn't wait to be asked about upcoming events.
He monitors the calendar and surfaces things that need attention.

Examples:
- "You've got a night shift tonight at 20:00 — that's in 4 hours"
- "Amelia's birthday is in 3 weeks, nothing planned yet"
- "You haven't had a day off in 8 days based on your calendar"
- "Margot's 9 month check-up would be due around now"

This runs as part of the autonomous loop and creates alerts
that Tony injects into his next response.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def analyse_upcoming_schedule() -> List[Dict]:
    """
    Tony reviews upcoming calendar events and identifies
    things that need proactive attention.
    """
    try:
        from app.core.calendar_service import get_upcoming_events
        from app.core.gmail_service import get_all_accounts
        accounts = get_all_accounts()
        if not accounts:
            return []

        all_events = []
        for account in accounts[:2]:  # Check first 2 accounts
            events = await get_upcoming_events(account, days=14)
            all_events.extend(events)

        if not all_events:
            return []

        events_text = "\n".join(
            f"- {e.get('title','')}: {e.get('start','')}"
            for e in all_events[:20]
        )

        now = datetime.utcnow().isoformat()

        prompt = f"""Tony is reviewing Matthew's upcoming calendar to proactively surface things that need attention.

Current time (UTC): {now}

Matthew's context:
- Works night shifts at Sid Bailey Care Home (shifts typically 20:00-08:00)
- Wife Georgina, daughters Amelia (4, born 7 Mar 2021) and Margot (9 months, born 20 Jul 2025)
- Building Nova app in spare time
- Recent bereavement (father died 17 days ago)

Upcoming events:
{events_text}

Identify 1-3 things Tony should proactively mention to Matthew. Consider:
- Events happening today or tomorrow that need preparation
- Upcoming family events that might need planning
- Patterns (e.g. many night shifts in a row)
- Anything that looks like it could be missed or needs attention

Only flag genuinely useful things. Don't manufacture concern.

Respond in JSON:
{{
    "insights": [
        {{
            "urgency": "today|soon|upcoming",
            "message": "what Tony should tell Matthew",
            "reason": "why this matters"
        }}
    ]
}}

If nothing noteworthy: {{"insights": []}}"""

        result = await gemini_json(prompt, task="analysis", max_tokens=512)
        return result.get("insights", []) if result else []

    except Exception as e:
        print(f"[PROACTIVE_SCHEDULER] Failed: {e}")
        return []


async def check_family_dates() -> List[Dict]:
    """
    Tony monitors important family dates and surfaces them early.
    """
    today = datetime.utcnow()
    alerts = []

    important_dates = [
        {"name": "Georgina's birthday", "month": 2, "day": 26, "type": "birthday"},
        {"name": "Amelia's birthday", "month": 3, "day": 7, "type": "birthday"},
        {"name": "Margot's birthday", "month": 7, "day": 20, "type": "birthday"},
        {"name": "Tony Lainton's anniversary", "month": 4, "day": 2, "type": "anniversary"},
    ]

    for date_info in important_dates:
        # Check if date is coming up in next 30 days
        this_year = today.replace(month=date_info["month"], day=date_info["day"])
        if this_year < today:
            this_year = this_year.replace(year=today.year + 1)

        days_until = (this_year - today).days

        if 0 <= days_until <= 30:
            urgency = "today" if days_until == 0 else "soon" if days_until <= 7 else "upcoming"
            alerts.append({
                "urgency": urgency,
                "message": f"{date_info['name']} is {'today' if days_until == 0 else f'in {days_until} days'} ({this_year.strftime('%d %B')})",
                "reason": f"Important {date_info['type']} to be aware of"
            })

    return alerts


async def run_proactive_scheduling():
    """
    Full proactive scheduling run.
    Creates alerts for things Tony should surface.
    """
    insights = []

    try:
        schedule_insights = await analyse_upcoming_schedule()
        insights.extend(schedule_insights)
    except Exception as e:
        print(f"[PROACTIVE_SCHEDULER] Schedule analysis failed: {e}")

    try:
        family_alerts = await check_family_dates()
        insights.extend(family_alerts)
    except Exception as e:
        print(f"[PROACTIVE_SCHEDULER] Family dates failed: {e}")

    # Create alerts for each insight
    for insight in insights:
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="scheduling",
                title=insight.get("message", "")[:100],
                body=insight.get("reason", ""),
                priority="high" if insight.get("urgency") == "today" else "normal",
                source="proactive_scheduler"
            )
        except Exception as e:
            print(f"[PROACTIVE_SCHEDULER] Alert creation failed: {e}")

    if insights:
        print(f"[PROACTIVE_SCHEDULER] Created {len(insights)} scheduling insights")

    return insights
