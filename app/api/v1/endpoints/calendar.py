"""Tony's Calendar endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.calendar_service import (
    get_upcoming_events, create_event, get_todays_schedule,
    get_calendar_auth_url
)
from app.core.gmail_service import get_all_accounts

router = APIRouter()

@router.get("/calendar/auth")
async def calendar_auth(email: str, _=Depends(verify_token)):
    """Get OAuth URL to grant Tony calendar access."""
    url = get_calendar_auth_url(email)
    return {"auth_url": url, "note": "Open this URL and grant access. Uses same token as Gmail if scopes match."}

@router.get("/calendar/today")
async def calendar_today(_=Depends(verify_token)):
    """Tony gets today's schedule across all accounts."""
    accounts = get_all_accounts()
    schedules = []
    for account in accounts:
        try:
            schedule = await get_todays_schedule(account)
            if "Nothing" not in schedule:
                schedules.append(schedule)
        except Exception as e:
            schedules.append(f"[{account}] Calendar error: {e}")
    return {"schedule": "\n\n".join(schedules) if schedules else "Nothing in the calendar today."}

@router.get("/calendar/upcoming")
async def calendar_upcoming(days: int = 7, _=Depends(verify_token)):
    """Tony gets upcoming events for the next N days."""
    accounts = get_all_accounts()
    all_events = []
    for account in accounts:
        try:
            events = await get_upcoming_events(account, days)
            all_events.extend(events)
        except Exception as e:
            print(f"[CALENDAR] {account}: {e}")
    all_events.sort(key=lambda x: x.get("start", ""))
    return {"events": all_events, "count": len(all_events)}

@router.post("/calendar/create")
async def calendar_create(
    email: str, title: str, start: str, end: str,
    description: str = "", location: str = "",
    _=Depends(verify_token)
):
    """Tony creates a calendar event."""
    return await create_event(email, title, start, end, description, location)

@router.get("/calendar/test")
async def calendar_test(_=Depends(verify_token)):
    """Test calendar access."""
    accounts = get_all_accounts()
    results = {}
    for account in accounts:
        try:
            events = await get_upcoming_events(account, days=1)
            results[account] = {"ok": True, "events_today": len(events)}
        except Exception as e:
            results[account] = {"ok": False, "error": str(e)}
    return {"accounts": results}
