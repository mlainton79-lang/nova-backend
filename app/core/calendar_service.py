"""
Tony's Calendar System.
Uses Google Calendar API — same OAuth as Gmail.
Tony reads your schedule, adds events, spots conflicts, reminds you.
"""
import os
import httpx
import psycopg2
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def get_calendar_auth_url(email: str) -> str:
    """Generate OAuth URL for Calendar access."""
    import urllib.parse
    params = {
        "client_id": GMAIL_CLIENT_ID,
        "redirect_uri": f"https://web-production-be42b.up.railway.app/api/v1/calendar/auth/callback",
        "response_type": "code",
        "scope": " ".join([
            "https://mail.google.com/",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/userinfo.email"
        ]),
        "access_type": "offline",
        "prompt": "consent",
        "state": email
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


async def get_calendar_token(email: str) -> Optional[str]:
    """Get access token for calendar — reuse Gmail token if scopes cover it."""
    try:
        from app.core.gmail_service import refresh_access_token
        return await refresh_access_token(email)
    except Exception:
        return None


async def get_upcoming_events(email: str, days: int = 7) -> List[Dict]:
    """Get upcoming calendar events for the next N days."""
    token = await get_calendar_token(email)
    if not token:
        return []

    now = datetime.utcnow().isoformat() + "Z"
    end = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": now,
                    "timeMax": end,
                    "singleEvents": True,
                    "orderBy": "startTime",
                    "maxResults": 20
                }
            )
            if r.status_code != 200:
                print(f"[CALENDAR] Events fetch failed: {r.status_code} {r.text[:200]}")
                return []

            events = r.json().get("items", [])
            result = []
            for e in events:
                start = e.get("start", {})
                result.append({
                    "id": e.get("id"),
                    "title": e.get("summary", "(no title)"),
                    "start": start.get("dateTime", start.get("date", "")),
                    "end": e.get("end", {}).get("dateTime", ""),
                    "location": e.get("location", ""),
                    "description": e.get("description", ""),
                    "account": email
                })
            return result
    except Exception as e:
        print(f"[CALENDAR] Events fetch error: {e}")
        return []


async def create_event(email: str, title: str, start: str, end: str,
                        description: str = "", location: str = "") -> Dict:
    """Tony creates a calendar event."""
    token = await get_calendar_token(email)
    if not token:
        return {"ok": False, "error": "No calendar token"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "summary": title,
                    "description": description,
                    "location": location,
                    "start": {"dateTime": start, "timeZone": "Europe/London"},
                    "end": {"dateTime": end, "timeZone": "Europe/London"}
                }
            )
            if r.status_code == 200:
                return {"ok": True, "event": r.json()}
            return {"ok": False, "error": r.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def delete_event(email: str, event_id: str) -> Dict:
    """Delete a calendar event by id. Returns {ok, status_code, [error]}.

    Google's DELETE returns HTTP 204 on success (no body); 404/410 if the
    event was already cancelled or never existed; 403 if API not enabled
    or scope missing. The caller is responsible for verifying the event
    exists and belongs to the right calendar BEFORE calling this — the
    function itself just performs the DELETE.
    """
    token = await get_calendar_token(email)
    if not token:
        return {"ok": False, "error": "No calendar token"}
    if not event_id:
        return {"ok": False, "error": "event_id is required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code in (200, 204):
                return {"ok": True, "status_code": r.status_code}
            return {"ok": False, "status_code": r.status_code, "error": r.text[:300]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def update_event(email: str, event_id: str, updates: Dict) -> Dict:
    """PATCH a single calendar event with partial updates.

    `updates` is a dict whose keys map to Google Calendar event fields
    (`summary`, `description`, `location`, `start`, `end`). Time fields
    must be pre-shaped as `{"dateTime": "<ISO>", "timeZone": "Europe/London"}`
    by the caller — the dispatcher does that shaping from its extractor
    output.

    Returns `{ok, event}` on 200, `{ok: False, status_code, error}` otherwise.
    Pre-flight verify-by-GET (does this event exist? does it match the
    intended target?) is the dispatcher's responsibility, not this helper's
    — same separation as delete_event.
    """
    token = await get_calendar_token(email)
    if not token:
        return {"ok": False, "error": "No calendar token"}
    if not event_id:
        return {"ok": False, "error": "event_id is required"}
    if not isinstance(updates, dict) or not updates:
        return {"ok": False, "error": "updates dict is required and must be non-empty"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.patch(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=updates,
            )
            if r.status_code == 200:
                return {"ok": True, "event": r.json()}
            return {"ok": False, "status_code": r.status_code, "error": r.text[:300]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def get_event(email: str, event_id: str) -> Dict:
    """Fetch a single calendar event by id. Used by the calendar_delete
    dispatcher to verify the event exists and matches expectations BEFORE
    issuing DELETE — same pattern as the manual one-shot deletion of the
    R2.4+ test event.
    """
    token = await get_calendar_token(email)
    if not token:
        return {"ok": False, "error": "No calendar token"}
    if not event_id:
        return {"ok": False, "error": "event_id is required"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code == 200:
                return {"ok": True, "event": r.json()}
            return {"ok": False, "status_code": r.status_code, "error": r.text[:300]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _samsung_today_range(now: Optional[datetime] = None):
    london = ZoneInfo("Europe/London")
    current = now or datetime.now(london)
    if current.tzinfo is None:
        current = current.replace(tzinfo=london)
    current = current.astimezone(london)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _format_samsung_time(event: Dict) -> str:
    start = event.get("start") or ""
    if event.get("all_day"):
        return "All day"
    try:
        parsed = datetime.fromisoformat(start)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("Europe/London"))
        return parsed.strftime("%H:%M")
    except Exception:
        return start[:16].replace("T", " ")


def get_grounded_samsung_todays_schedule(now: Optional[datetime] = None) -> Dict:
    """
    Return today's Samsung calendar schedule after grounding against fetched rows.

    This is read-only. It never creates, updates, or deletes calendar items.
    """
    from app.core import calendar_grounding_contract as grounding
    from app.core.samsung_calendar import get_events_between

    start, end = _samsung_today_range(now)
    events = get_events_between(start, end)
    decision = grounding.evaluate_calendar_grounding(start, end, events)

    if not decision.allowed:
        return {
            "ok": False,
            "status": decision.status,
            "reason": decision.reason,
            "events": events,
            "schedule": "Calendar is unavailable right now.",
        }

    if not events:
        return {
            "ok": True,
            "status": decision.status,
            "reason": decision.reason,
            "events": [],
            "schedule": "Nothing in the Samsung calendar today.",
        }

    lines = ["Today's Samsung calendar:"]
    for event in events:
        line = f"- {_format_samsung_time(event)} - {event.get('title') or '(no title)'}"
        if event.get("location"):
            line += f" ({event['location']})"
        lines.append(line)
    return {
        "ok": True,
        "status": decision.status,
        "reason": decision.reason,
        "events": events,
        "schedule": "\n".join(lines),
    }


async def get_todays_schedule(email: str) -> str:
    """Get today's events as a readable summary."""
    events = await get_upcoming_events(email, days=1)
    if not events:
        return "Nothing in the calendar today."

    lines = [f"📅 Today's schedule ({email.split('@')[0]}):"]
    for e in events:
        start = e["start"][:16].replace("T", " ") if "T" in e["start"] else e["start"]
        lines.append(f"• {start} — {e['title']}")
        if e.get("location"):
            lines.append(f"  📍 {e['location']}")
    return "\n".join(lines)
