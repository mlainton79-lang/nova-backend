"""
Tony's Calendar System.
Uses Google Calendar API — same OAuth as Gmail.
Tony reads your schedule, adds events, spots conflicts, reminds you.
"""
import os
import httpx
import psycopg2
from datetime import datetime, timedelta
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
