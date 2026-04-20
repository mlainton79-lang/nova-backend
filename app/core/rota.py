"""
Matthew's rota — permanent shift pattern.

Sid Bailey Care Home, Brampton.
Pattern: 3 on, 3 off. Shifts are 20:00 -> 08:00.
Anchor: 24 April 2026 is the first shift of the new pattern.

From this we can calculate:
- Is Matthew working right now?
- Has he just come off a shift?
- Is his next shift soon?
- What's his rota for a given date?

Tony should never guess "have you just come off a shift?" — he should KNOW.
"""
from datetime import datetime, timedelta, date, time
from typing import Dict, Optional
import os


# Anchor date — the first day of a 3-on block in the current pattern
ROTA_ANCHOR_DATE = date(2026, 4, 24)
SHIFT_START_HOUR = 20  # 20:00
SHIFT_END_HOUR = 8     # 08:00 next morning
CYCLE_DAYS = 6         # 3 on + 3 off
ON_DAYS = 3            # first 3 days of cycle are on


def uk_now() -> datetime:
    """Current time in UK timezone."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London"))
    except Exception:
        return datetime.utcnow()


def _cycle_position(check_date: date) -> int:
    """Return position in cycle (0-5) for a given date. 0-2 = on, 3-5 = off."""
    delta_days = (check_date - ROTA_ANCHOR_DATE).days
    return delta_days % CYCLE_DAYS


def is_working_on_date(check_date: date) -> bool:
    """Does Matthew's shift START on this date? (He works 20:00 this date -> 08:00 next)"""
    if check_date < ROTA_ANCHOR_DATE:
        return False
    return _cycle_position(check_date) < ON_DAYS


def is_currently_on_shift(now: Optional[datetime] = None) -> bool:
    """Is Matthew actively at work right now (between 20:00 and 08:00 on a shift day)?"""
    if now is None:
        now = uk_now()

    today = now.date()
    yesterday = today - timedelta(days=1)

    # Evening of a shift-start day (20:00 onwards)
    if is_working_on_date(today) and now.hour >= SHIFT_START_HOUR:
        return True
    # Morning after a shift-start day (before 08:00)
    if is_working_on_date(yesterday) and now.hour < SHIFT_END_HOUR:
        return True
    return False


def just_finished_shift(now: Optional[datetime] = None, hours_since: int = 4) -> bool:
    """Did Matthew finish a shift within the last `hours_since` hours?"""
    if now is None:
        now = uk_now()
    # Shift ends at 08:00. If it's between 08:00 and 08:00+hours_since on the morning
    # after a shift-start day, he just got in.
    yesterday = now.date() - timedelta(days=1)
    if is_working_on_date(yesterday) and SHIFT_END_HOUR <= now.hour < (SHIFT_END_HOUR + hours_since):
        return True
    return False


def next_shift_start(now: Optional[datetime] = None) -> Optional[datetime]:
    """When does the next shift start? Returns datetime or None if past anchor isn't reached."""
    if now is None:
        now = uk_now()
    # Look ahead up to 7 days
    for offset in range(0, 8):
        check_date = now.date() + timedelta(days=offset)
        if check_date < ROTA_ANCHOR_DATE:
            continue
        if is_working_on_date(check_date):
            shift_start = datetime.combine(check_date, time(SHIFT_START_HOUR, 0))
            # Attach timezone if possible
            try:
                from zoneinfo import ZoneInfo
                shift_start = shift_start.replace(tzinfo=ZoneInfo("Europe/London"))
            except Exception:
                pass
            if shift_start > now:
                return shift_start
    return None


def rota_status_for_prompt() -> str:
    """Compact string describing Matthew's current rota status — for injection into Tony's prompt."""
    now = uk_now()
    today = now.date()

    lines = []

    # Pattern description
    lines.append(
        f"Matthew's rota (Sid Bailey Care Home): 3 on, 3 off. Shifts 20:00-08:00. "
        f"Current pattern anchored on {ROTA_ANCHOR_DATE.isoformat()}."
    )

    # Current state
    if today < ROTA_ANCHOR_DATE:
        days_until = (ROTA_ANCHOR_DATE - today).days
        lines.append(
            f"Right now: Matthew is OFF. Pattern doesn't start until {ROTA_ANCHOR_DATE.strftime('%A %d %B')} "
            f"({days_until} day{'s' if days_until != 1 else ''} away)."
        )
    elif is_currently_on_shift(now):
        lines.append(f"Right now: Matthew IS AT WORK. On shift until 08:00.")
    elif just_finished_shift(now, hours_since=3):
        lines.append(f"Right now: Matthew just finished a shift a few hours ago.")
    elif is_working_on_date(today):
        if now.hour < SHIFT_START_HOUR:
            hours_until = SHIFT_START_HOUR - now.hour
            lines.append(f"Right now: Matthew is off, but has a shift tonight at 20:00 ({hours_until}h away).")
        else:
            lines.append(f"Right now: Matthew is OFF (evening, pre-shift window).")
    else:
        lines.append(f"Right now: Matthew is OFF today. Not working tonight.")

    # Next 3 days
    preview = []
    for offset in range(3):
        check_date = today + timedelta(days=offset)
        label = "Today" if offset == 0 else "Tomorrow" if offset == 1 else check_date.strftime("%A")
        if check_date < ROTA_ANCHOR_DATE:
            preview.append(f"{label}: off (pre-anchor)")
        elif is_working_on_date(check_date):
            preview.append(f"{label}: WORKING (20:00-08:00)")
        else:
            preview.append(f"{label}: off")
    lines.append("Upcoming: " + " | ".join(preview))

    # Next shift start
    nxt = next_shift_start(now)
    if nxt and not is_currently_on_shift(now):
        days_away = (nxt.date() - today).days
        if days_away == 0:
            lines.append(f"Next shift: tonight at 20:00.")
        elif days_away == 1:
            lines.append(f"Next shift: tomorrow at 20:00.")
        else:
            lines.append(f"Next shift: {nxt.strftime('%A %d %B')} at 20:00.")

    return "\n".join(lines)


def get_rota_for_date_range(start: date, end: date) -> Dict[str, bool]:
    """Return dict of ISO-date -> working True/False for a date range."""
    result = {}
    current = start
    while current <= end:
        result[current.isoformat()] = is_working_on_date(current)
        current += timedelta(days=1)
    return result
