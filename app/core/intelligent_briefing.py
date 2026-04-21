"""
Tony's Intelligent Briefing.

Replaces the current 'bullet list of alerts + goals' with a real briefing
that synthesises:
  - Time of day + shift status
  - Weather
  - Unread high-priority emails (from triage)
  - Today's calendar events
  - Family dates approaching
  - Recent Tony activity (builds, tasks)
  - Unresolved alerts
  - Active skills/capabilities
  - Fact-based context (who's birthday is next, etc.)

Into a SINGLE coherent paragraph or short structure that feels like a
trusted assistant giving you a real brief, not a database readout.
"""
import os
import json
import httpx
import psycopg2
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def gather_state() -> Dict:
    """Pull every useful signal from DB. Each query isolated."""
    state = {"now": datetime.utcnow().isoformat()}

    # Time of day + shift status
    try:
        from app.core.rota import is_currently_on_shift, next_shift_start
        from datetime import timezone
        on_shift_now = is_currently_on_shift()
        nxt = next_shift_start()
        hours_to_next = None
        if nxt:
            # Normalise to UTC; next_shift_start may return tz-aware UK time
            now_utc = datetime.now(timezone.utc)
            ns = nxt if nxt.tzinfo else nxt.replace(tzinfo=timezone.utc)
            hours_to_next = (ns - now_utc).total_seconds() / 3600
        state["shift"] = {
            "on_shift_now": on_shift_now,
            "next_shift_in_hours": round(hours_to_next, 1) if hours_to_next is not None else None,
            "next_shift_start": nxt.isoformat() if nxt else None,
        }
    except Exception as e:
        state["shift"] = None
        state["shift_error"] = str(e)

    # Urgent alerts
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            SELECT title, body, priority, created_at FROM tony_alerts
            WHERE read = FALSE
              AND source != 'tony_push'
              AND title NOT LIKE '%Tony — Urgent%'
              AND created_at > NOW() - INTERVAL '48 hours'
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END,
                     created_at DESC LIMIT 5
        """)
        state["alerts"] = [
            {"title": r[0], "body": (r[1] or "")[:200],
             "priority": r[2], "created_at": str(r[3])}
            for r in cur.fetchall()
        ]
        cur.close()
        conn.close()
    except Exception:
        state["alerts"] = []

    # Urgent emails from triage
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT sender, subject, urgency, summary, action, reply_draft
            FROM tony_email_triage
            WHERE urgency IN ('urgent','normal')
              AND triaged_at > NOW() - INTERVAL '48 hours'
            ORDER BY CASE urgency WHEN 'urgent' THEN 1 ELSE 2 END,
                     triaged_at DESC LIMIT 5
        """)
        state["emails"] = [
            {"sender": r[0], "subject": r[1], "urgency": r[2],
             "summary": r[3], "action": r[4], "has_draft": bool(r[5])}
            for r in cur.fetchall()
        ]
        cur.close()
        conn.close()
    except Exception:
        state["emails"] = []

    # Today's calendar events (uses get_upcoming_events which needs an email)
    try:
        from app.core.calendar_service import get_upcoming_events
        # Use Matthew's primary gmail — fall back silently if not configured
        primary_email = os.environ.get("MATTHEW_GMAIL_PRIMARY", "mlainton79@gmail.com")
        events = await get_upcoming_events(primary_email, days=1)
        # Filter to just today (datetime already imported at top)
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        today_events = [e for e in events
                        if today_str in str(e.get("start", e.get("start_time", "")))]
        state["calendar"] = today_events[:5]
    except Exception as e:
        state["calendar"] = []
        state["calendar_error"] = str(e)[:100]

    # Upcoming family dates
    try:
        today = date.today()
        dates = [
            (date(today.year, 2, 26), "Georgina's birthday"),
            (date(today.year, 3, 7), "Amelia's birthday"),
            (date(today.year, 7, 20), "Margot's birthday"),
            (date(today.year, 6, 4), "Dad's birthday"),
            (date(today.year, 4, 2), "Anniversary of Dad's passing"),
        ]
        upcoming = []
        for d, name in dates:
            if d < today:
                d = d.replace(year=today.year + 1)
            days = (d - today).days
            if 0 <= days <= 14:
                upcoming.append({"name": name, "days": days, "date": str(d)})
        state["family_dates"] = upcoming
    except Exception:
        state["family_dates"] = []

    # Tony's recent autonomous activity
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT capability_name, status FROM tony_capability_requests
            WHERE created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 5
        """)
        state["recent_builds"] = [
            {"name": r[0], "status": r[1]} for r in cur.fetchall()
        ]
        cur.close()

        cur = conn.cursor()
        cur.execute("""
            SELECT task_type, status FROM tony_task_queue
            WHERE completed_at > NOW() - INTERVAL '24 hours'
               OR status IN ('running', 'queued')
            ORDER BY created_at DESC LIMIT 5
        """)
        state["recent_tasks"] = [
            {"type": r[0], "status": r[1]} for r in cur.fetchall()
        ]
        cur.close()
        conn.close()
    except Exception:
        state["recent_builds"] = []
        state["recent_tasks"] = []

    # Weather (location-aware)
    try:
        from app.core.weather import get_weather_summary
        state["weather"] = await get_weather_summary()
    except Exception:
        state["weather"] = None

    # Eval pass rate (recent)
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT pass_rate, run_at FROM tony_eval_runs
            ORDER BY run_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            state["last_eval"] = {"pass_rate": row[0], "when": str(row[1])}
        cur.close()
        conn.close()
    except Exception:
        pass

    # Improvement proposals waiting
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM tony_improvement_proposals
            WHERE status = 'pending'
        """)
        state["pending_proposals"] = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception:
        state["pending_proposals"] = 0

    return state


async def synthesise_briefing(state: Dict) -> str:
    """Turn raw state into a readable morning brief using Gemini."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _fallback_briefing(state)

    # Curate state into compact form for the LLM
    facts = []

    # Time context
    now_uk = datetime.utcnow() + timedelta(hours=1)  # BST rough
    hour = now_uk.hour
    if hour < 6:
        facts.append(f"Time: {now_uk.strftime('%H:%M')} — early morning")
    elif hour < 12:
        facts.append(f"Time: {now_uk.strftime('%H:%M')} — morning")
    elif hour < 17:
        facts.append(f"Time: {now_uk.strftime('%H:%M')} — afternoon")
    elif hour < 22:
        facts.append(f"Time: {now_uk.strftime('%H:%M')} — evening")
    else:
        facts.append(f"Time: {now_uk.strftime('%H:%M')} — late")

    shift = state.get("shift")
    if shift:
        if shift.get("on_shift_now"):
            facts.append("On shift now")
        elif shift.get("next_shift_in_hours") is not None:
            h = shift["next_shift_in_hours"]
            if h is not None and h < 24:
                facts.append(f"Next shift in {int(h)}h")

    weather = state.get("weather")
    if weather:
        facts.append(f"Weather: {weather}")

    alerts = state.get("alerts", [])
    if alerts:
        urgent = [a for a in alerts if a["priority"] == "urgent"]
        if urgent:
            facts.append(f"URGENT ALERTS: {len(urgent)}")
            for a in urgent[:3]:
                facts.append(f"  - {a['title']}: {a['body'][:100]}")
        other = [a for a in alerts if a["priority"] != "urgent"]
        if other:
            facts.append(f"Other alerts: {len(other)}")

    emails = state.get("emails", [])
    if emails:
        urgent_emails = [e for e in emails if e["urgency"] == "urgent"]
        if urgent_emails:
            facts.append(f"URGENT EMAILS: {len(urgent_emails)}")
            for e in urgent_emails[:3]:
                facts.append(f"  - {e['sender']}: {e['summary']}")
        other_emails = [e for e in emails if e["urgency"] == "normal"]
        if other_emails:
            facts.append(f"Normal emails: {len(other_emails)}")

    cal = state.get("calendar", [])
    if cal:
        facts.append(f"Calendar today: {len(cal)} events")
        for e in cal[:3]:
            summary = e.get("summary", "")
            start = e.get("start_time", e.get("start", ""))
            facts.append(f"  - {start} {summary}")

    family = state.get("family_dates", [])
    for f in family:
        if f["days"] == 0:
            facts.append(f"TODAY: {f['name']}")
        elif f["days"] == 1:
            facts.append(f"Tomorrow: {f['name']}")
        else:
            facts.append(f"In {f['days']} days: {f['name']}")

    builds = state.get("recent_builds", [])
    built_names = [b["name"] for b in builds if b["status"] in ("built", "active")]
    if built_names:
        facts.append(f"Tony built overnight: {', '.join(built_names[:3])}")

    if state.get("pending_proposals", 0) > 0:
        facts.append(f"Self-improvement proposals waiting: {state['pending_proposals']}")

    facts_text = "\n".join(facts) if facts else "No significant events."

    prompt = f"""You are writing Matthew's morning brief. Speak AS Tony — warm, direct, short sentences, British English, no pet names. Don't greet. Don't list bullet points by default. Deliver the brief in natural prose.

Rules:
- If there's URGENT stuff, lead with it. Short, clear, what to do.
- If there's just routine info, keep it to 2-3 sentences.
- If there's nothing much, say so briefly. "Quiet one so far. Nothing needing you."
- Reference family members by name, not role.
- Don't narrate the time ('given it's 9am...'). Don't say 'Good morning'.
- NEVER mention CCJ, debt, legal cases, Western Circle. These are banned topics.
- Don't list everything. Pick what matters. If emails aren't urgent, mention the count and move on.

State:
{facts_text}

Write the brief. One short paragraph. No headers, no bullets, no 'Good morning'.
"""

    try:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 400, "temperature": 0.4}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            # Strip any accidental 'Good morning' or bullet prefixes
            for opener in ["Good morning", "Morning.", "Morning,", "Morning! ", "Morning, "]:
                if text.startswith(opener):
                    text = text[len(opener):].lstrip(" ,.")
            return text
    except Exception as e:
        print(f"[BRIEFING] LLM synthesis failed: {e}")
        return _fallback_briefing(state)


def _fallback_briefing(state: Dict) -> str:
    """Plain text briefing if LLM synthesis fails."""
    parts = []
    alerts = state.get("alerts", [])
    urgent = [a for a in alerts if a["priority"] == "urgent"]
    if urgent:
        parts.append(f"{len(urgent)} urgent alert(s).")
    emails = state.get("emails", [])
    urgent_emails = [e for e in emails if e["urgency"] == "urgent"]
    if urgent_emails:
        parts.append(f"{len(urgent_emails)} urgent email(s).")
    cal = state.get("calendar", [])
    if cal:
        parts.append(f"{len(cal)} on calendar today.")
    for f in state.get("family_dates", []):
        if f["days"] <= 2:
            parts.append(f"{f['name']} in {f['days']} day(s).")
    if not parts:
        return "Quiet one so far. Nothing needing you."
    return " ".join(parts)


async def get_intelligent_briefing() -> Dict:
    """Full briefing pipeline. Returns {text, state}."""
    state = await gather_state()
    text = await synthesise_briefing(state)
    return {"ok": True, "briefing": text, "state": state}
