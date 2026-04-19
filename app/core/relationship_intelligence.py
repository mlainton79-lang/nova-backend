"""
Tony's Relationship Intelligence.

Tony understands the key people in Matthew's life
and tracks relationship context over time.

Key relationships Tony monitors:
- Georgina (wife) - upcoming dates, what she might need
- Amelia (4yo daughter) - school, activities, development
- Margot (9mo daughter) - health milestones, appointments
- Christine (mother) - contact patterns, wellbeing
- Work colleagues at Sid Bailey

Tony notices:
- Upcoming birthdays and anniversaries
- Whether Matthew has mentioned a person recently (and if not, why)
- Relationship stress signals in conversation
- Gift/celebration opportunities
- Important dates coming up

This makes Tony a genuine supporter of Matthew's family life,
not just a productivity tool.
"""
import os
import psycopg2
from datetime import datetime, timedelta, date
from typing import Dict, List
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


FAMILY_CALENDAR = [
    {"name": "Georgina", "relation": "wife", "birthday": (2, 26), "anniversary": None},
    {"name": "Amelia", "relation": "daughter", "birthday": (3, 7), "age_in_2026": 5},
    {"name": "Margot", "relation": "daughter", "birthday": (7, 20), "age_in_2026": 1},
    {"name": "Tony Lainton (Dad)", "relation": "late father", "birthday": (6, 4), "passed": (4, 2)},
    {"name": "Christine", "relation": "mother", "birthday": None},
]


def get_upcoming_family_dates(days_ahead: int = 30) -> List[Dict]:
    """Get all family dates coming up."""
    today = date.today()
    upcoming = []
    
    for person in FAMILY_CALENDAR:
        if person.get("birthday"):
            month, day = person["birthday"]
            birthday_this_year = date(today.year, month, day)
            if birthday_this_year < today:
                birthday_this_year = date(today.year + 1, month, day)
            
            days_until = (birthday_this_year - today).days
            if 0 <= days_until <= days_ahead:
                upcoming.append({
                    "name": person["name"],
                    "relation": person["relation"],
                    "event": "birthday",
                    "date": birthday_this_year.strftime("%d %B"),
                    "days_until": days_until,
                    "urgency": "today" if days_until == 0 else "soon" if days_until <= 7 else "upcoming"
                })
        
        if person.get("passed"):
            month, day = person["passed"]
            anniversary = date(today.year, month, day)
            if anniversary < today:
                anniversary = date(today.year + 1, month, day)
            days_until = (anniversary - today).days
            if 0 <= days_until <= days_ahead:
                upcoming.append({
                    "name": person["name"],
                    "relation": person["relation"],
                    "event": "anniversary",
                    "date": anniversary.strftime("%d %B"),
                    "days_until": days_until,
                    "urgency": "today" if days_until == 0 else "soon" if days_until <= 7 else "upcoming"
                })
    
    return sorted(upcoming, key=lambda x: x["days_until"])


async def get_gift_suggestions(person: str, occasion: str, budget: str = "£20-50") -> List[str]:
    """Tony suggests thoughtful gifts based on what he knows."""
    prompt = f"""Suggest 3 thoughtful gift ideas for {person} ({occasion}).

Budget: {budget}
Context: Matthew Lainton, care worker in Rotherham, building AI app.

Suggestions should be:
- Practical and thoughtful, not generic
- Available online (UK) or locally
- Within budget
- Appropriate for the relationship

Just list 3 specific suggestions, no explanation."""

    result = await gemini_json(
        f"Return a JSON array of 3 gift suggestions for {person}: {prompt}",
        task="analysis", max_tokens=200
    )
    return result if isinstance(result, list) else []


async def check_amelia_milestones() -> List[str]:
    """Track Amelia's developmental milestones and school readiness."""
    # Amelia turns 5 in March 2026 - approaching school age
    today = date.today()
    amelia_birthday = date(today.year, 3, 7)
    if amelia_birthday < today:
        amelia_birthday = date(today.year + 1, 3, 7)
    
    days_to_birthday = (amelia_birthday - today).days
    alerts = []
    
    if days_to_birthday <= 60:
        alerts.append(f"Amelia turns 5 in {days_to_birthday} days — school registration may be needed")
    
    # Check if September school start is approaching
    sept = date(today.year, 9, 1)
    if today.month < 9 and (sept - today).days <= 120:
        alerts.append("Amelia approaching school age — school applications typically due January/February")
    
    return alerts


async def check_margot_health() -> List[str]:
    """Track Margot's health check schedule."""
    # Margot born 20 July 2025, so approximately 9 months old April 2026
    today = date.today()
    margot_birthday = date(2025, 7, 20)
    age_months = (today - margot_birthday).days // 30
    
    alerts = []
    
    # Standard UK health visitor checks
    health_checks = {
        6: "6-8 month developmental review",
        12: "12 month review",
        24: "2-year review",
        36: "3-year review"
    }
    
    for check_month, check_name in health_checks.items():
        if abs(age_months - check_month) <= 1:
            alerts.append(f"Margot is {age_months} months — {check_name} may be due")
    
    return alerts


async def run_relationship_intelligence() -> Dict:
    """Full relationship intelligence run."""
    results = {}
    
    # Upcoming dates
    upcoming = get_upcoming_family_dates(30)
    results["upcoming_dates"] = upcoming
    
    # Create alerts for imminent dates
    for event in upcoming:
        if event["days_until"] <= 14:
            try:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="family_date",
                    title=f"{event['name']}'s {event['event']} — {event['date']}",
                    body=f"{event['days_until']} days away. {event['relation'].capitalize()}.",
                    priority="high" if event["days_until"] <= 7 else "normal",
                    source="relationship_intelligence"
                )
            except Exception:
                pass
    
    # Amelia milestones
    amelia_alerts = await check_amelia_milestones()
    for alert in amelia_alerts:
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="child_milestone",
                title="Amelia milestone",
                body=alert,
                priority="normal",
                source="relationship_intelligence"
            )
        except Exception:
            pass
    results["amelia_alerts"] = amelia_alerts
    
    # Margot health checks
    margot_alerts = await check_margot_health()
    for alert in margot_alerts:
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="child_health",
                title="Margot health check",
                body=alert,
                priority="normal",
                source="relationship_intelligence"
            )
        except Exception:
            pass
    results["margot_alerts"] = margot_alerts
    
    if upcoming or amelia_alerts or margot_alerts:
        print(f"[RELATIONSHIP_INTEL] {len(upcoming)} upcoming dates, {len(amelia_alerts + margot_alerts)} child alerts")
    
    return results
