"""
Samsung calendar event store.

Persistent backing for events posted from the Android device's calendar.
proactive_scheduler.check_calendar_for_today() reads from this table;
this module is the writer.
"""
import os
import re
import asyncio
import psycopg2
from datetime import datetime, date, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from psycopg2 import errors as psycopg2_errors

from app.observability import EventSeverity, record_run_event


UK_TZ = ZoneInfo("Europe/London")
MAX_PROMPT_EVENTS = 12


_CALENDAR_QUERY_PATTERNS = (
    re.compile(r"\b(calendar|schedule|diary|appointments?|meetings?|shifts?)\b"),
    re.compile(r"\bwhat\s+have\s+i\s+got\b"),
    re.compile(r"\bwhat(?:'s|s| is)\s+on\b"),
    re.compile(r"\banything\s+on\b"),
    re.compile(r"\bam\s+i\s+(free|available)\b"),
    re.compile(
        r"\bevents?\b.*\b(today|tomorrow|weekend|week|month|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    ),
)

_STOPWORDS = {
    "about", "after", "again", "anything", "appointment", "appointments",
    "available", "before", "calendar", "check", "diary", "event", "events",
    "find", "free", "from", "got", "have", "into", "look", "meeting", "meetings",
    "monday", "month", "my", "next", "schedule", "search", "shift", "shifts", "show",
    "tell", "that", "this", "today", "tomorrow", "week", "weekend",
    "what", "what's", "whats", "when", "with", "your",
    "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}

_TEMPORAL_SEARCH_PHRASES = {
    "weekend", "the weekend", "this weekend", "next weekend",
    "week", "this week", "next week",
    "month", "this month", "next month",
    "today", "tomorrow",
}


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        sslmode="require",
        connect_timeout=10,
    )


def _record_read_failure(operation: str, e: Exception) -> None:
    record_run_event(
        event_type="samsung_calendar_read_failed",
        severity=EventSeverity.WARNING,
        subsystem="calendar.samsung.read",
        message=f"Samsung calendar {operation} failed",
        error_class=type(e).__name__,
        error_message=str(e)[:300],
    )


def _iso_or_none(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def init_samsung_calendar_table():
    """Create samsung_calendar_events if needed."""
    conn = None
    try:
        conn = get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS samsung_calendar_events (
                    event_id     TEXT        NOT NULL,
                    calendar_id  TEXT        NOT NULL,
                    title        TEXT,
                    start_time   TIMESTAMPTZ NOT NULL,
                    end_time     TIMESTAMPTZ,
                    all_day      BOOLEAN     NOT NULL DEFAULT FALSE,
                    location     TEXT,
                    description  TEXT,
                    start_ms     BIGINT      NOT NULL,
                    end_ms       BIGINT,
                    synced_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (calendar_id, event_id)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_samsung_calendar_start_time
                ON samsung_calendar_events(start_time)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_samsung_calendar_end_time
                ON samsung_calendar_events(end_time)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_samsung_calendar_synced_at
                ON samsung_calendar_events(synced_at)
            """)
        conn.commit()
        print("[SAMSUNG_CAL] Table initialised")
    except Exception as e:
        print(f"[SAMSUNG_CAL] Init failed: {e}")
    finally:
        if conn:
            conn.close()


def upsert_events(events: List[Dict]) -> int:
    """
    Atomically upsert a batch of Samsung calendar events.

    Each event dict must carry: event_id, calendar_id, title, start_ms,
    end_ms, all_day. May carry: location, description.

    Returns the number of events written. On error the whole batch is
    rolled back and the exception is re-raised.
    """
    if not events:
        return 0
    conn = get_conn()
    try:
        cur = conn.cursor()
        for ev in events:
            cur.execute("""
                INSERT INTO samsung_calendar_events
                    (event_id, calendar_id, title,
                     start_time, end_time, all_day,
                     location, description,
                     start_ms, end_ms, synced_at)
                VALUES
                    (%(event_id)s, %(calendar_id)s, %(title)s,
                     to_timestamp(%(start_ms)s / 1000.0),
                     CASE WHEN %(end_ms)s IS NULL THEN NULL
                          ELSE to_timestamp(%(end_ms)s / 1000.0) END,
                     %(all_day)s,
                     %(location)s, %(description)s,
                     %(start_ms)s, %(end_ms)s, NOW())
                ON CONFLICT (calendar_id, event_id) DO UPDATE SET
                    title       = EXCLUDED.title,
                    start_time  = EXCLUDED.start_time,
                    end_time    = EXCLUDED.end_time,
                    all_day     = EXCLUDED.all_day,
                    location    = EXCLUDED.location,
                    description = EXCLUDED.description,
                    start_ms    = EXCLUDED.start_ms,
                    end_ms      = EXCLUDED.end_ms,
                    synced_at   = NOW()
            """, {
                "event_id":    ev["event_id"],
                "calendar_id": ev["calendar_id"],
                "title":       ev.get("title"),
                "start_ms":    ev["start_ms"],
                "end_ms":      ev.get("end_ms"),
                "all_day":     ev["all_day"],
                "location":    ev.get("location"),
                "description": ev.get("description"),
            })
        conn.commit()
        cur.close()
        return len(events)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_legacy_read_event(row) -> Dict:
    event_id, calendar_id, title, start_time, end_time, all_day, location, description, synced_at = row
    event_key = f"{calendar_id}:{event_id}"
    return {
        "id": event_key,
        "event_id": event_key,
        "samsung_event_id": event_id,
        "calendar_id": calendar_id,
        "title": title or "(no title)",
        "start": _iso_or_none(start_time),
        "end": _iso_or_none(end_time),
        "all_day": bool(all_day),
        "location": location or "",
        "description": description or "",
        "synced_at": _iso_or_none(synced_at),
        "source": "samsung_calendar",
    }


def get_events_between(start_time: datetime, end_time: datetime, limit: int = 50) -> Optional[List[Dict]]:
    """
    Read Samsung calendar events in [start_time, end_time).

    Returns None on read failure so callers can distinguish "no fetched
    records" from a successful empty result. This helper keeps the legacy
    ISO-string event shape used by calendar_service's grounding contract.
    """
    if not start_time or not end_time or start_time >= end_time:
        return None

    safe_limit = max(1, min(int(limit or 50), 200))
    conn = None
    try:
        conn = get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, calendar_id, title, start_time, end_time,
                       all_day, location, description, synced_at
                FROM samsung_calendar_events
                WHERE start_time >= %s
                  AND start_time < %s
                ORDER BY start_time ASC, title ASC
                LIMIT %s
                """,
                (start_time, end_time, safe_limit),
            )
            return [_row_to_legacy_read_event(row) for row in cur.fetchall()]
    except psycopg2_errors.UndefinedTable:
        return None
    except Exception as e:
        _record_read_failure("read", e)
        return None
    finally:
        if conn:
            conn.close()


def get_read_status() -> Dict:
    """Return local Samsung calendar read status without exposing event data."""
    conn = None
    try:
        conn = get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::INT, MAX(synced_at)
                FROM samsung_calendar_events
                """
            )
            count, latest_synced_at = cur.fetchone()
            return {
                "ok": True,
                "event_count": int(count or 0),
                "latest_synced_at": _iso_or_none(latest_synced_at),
            }
    except psycopg2_errors.UndefinedTable:
        return {"ok": False, "event_count": 0, "latest_synced_at": None}
    except Exception as e:
        _record_read_failure("status", e)
        return {"ok": False, "event_count": 0, "latest_synced_at": None}
    finally:
        if conn:
            conn.close()


def is_calendar_query(message: str) -> bool:
    """Return whether a chat message needs Samsung calendar context."""
    msg = (message or "").lower()
    if not msg:
        return False
    return any(pattern.search(msg) for pattern in _CALENDAR_QUERY_PATTERNS)


def _local_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UK_TZ)


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def _month_bounds(today: date, offset: int = 0) -> Tuple[datetime, datetime]:
    month = today.month + offset
    year = today.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return _local_midnight(start), _local_midnight(end)


def _parse_explicit_date(msg: str, today: date) -> Optional[Tuple[datetime, datetime]]:
    patterns = (
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", "%Y-%m-%d"),
        (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", "%d/%m/%Y"),
    )
    for pattern, fmt in patterns:
        match = re.search(pattern, msg)
        if not match:
            continue
        try:
            found = datetime.strptime(match.group(0), fmt).date()
            start = _local_midnight(found)
            return start, start + timedelta(days=1)
        except ValueError:
            continue

    month_names = (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    )
    month_re = "|".join(month_names)
    for pattern in (
        rf"\b(\d{{1,2}})\s+({month_re})\b",
        rf"\b({month_re})\s+(\d{{1,2}})\b",
    ):
        match = re.search(pattern, msg)
        if not match:
            continue
        if match.group(1).isdigit():
            day = int(match.group(1))
            month = month_names.index(match.group(2)) + 1
        else:
            month = month_names.index(match.group(1)) + 1
            day = int(match.group(2))
        year = today.year
        try:
            found = date(year, month, day)
            if found < today - timedelta(days=7):
                found = date(year + 1, month, day)
            start = _local_midnight(found)
            return start, start + timedelta(days=1)
        except ValueError:
            continue
    return None


def infer_query_window(message: str) -> Tuple[datetime, datetime, str]:
    """Infer a bounded UK-local calendar window from a natural-language query."""
    msg = (message or "").lower()
    now = datetime.now(UK_TZ)
    today = now.date()

    explicit = _parse_explicit_date(msg, today)
    if explicit:
        return explicit[0], explicit[1], explicit[0].date().isoformat()

    if "tomorrow" in msg:
        start = _local_midnight(today + timedelta(days=1))
        return start, start + timedelta(days=1), "tomorrow"

    if "weekend" in msg:
        days_until_saturday = (5 - today.weekday()) % 7
        if "next weekend" in msg and today.weekday() <= 5:
            days_until_saturday += 7
        if "next weekend" not in msg and today.weekday() == 6:
            start = _local_midnight(today)
            return start, start + timedelta(days=1), "weekend"
        start = _local_midnight(today + timedelta(days=days_until_saturday))
        return start, start + timedelta(days=2), "next weekend" if "next weekend" in msg else "weekend"

    if "next week" in msg:
        start = _local_midnight(today + timedelta(days=(7 - today.weekday())))
        return start, start + timedelta(days=7), "next week"

    if "this week" in msg or "week ahead" in msg:
        start = _local_midnight(today)
        end = _local_midnight(today + timedelta(days=(7 - today.weekday())))
        return start, end, "this week"

    if "next month" in msg:
        start, end = _month_bounds(today, offset=1)
        return start, end, "next month"

    if "this month" in msg or "month ahead" in msg:
        start = _local_midnight(today)
        _, end = _month_bounds(today, offset=0)
        return start, end, "this month"

    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for name, weekday in weekdays.items():
        if name not in msg:
            continue
        delta = (weekday - today.weekday()) % 7
        if delta == 0 and "next" in msg:
            delta = 7
        start = _local_midnight(today + timedelta(days=delta))
        return start, start + timedelta(days=1), name

    if any(word in msg for word in ("upcoming", "next few days", "availability", "available", "free")):
        start = _local_midnight(today)
        return start, start + timedelta(days=7), "next 7 days"

    start = _local_midnight(today)
    return start, start + timedelta(days=1), "today"


def _extract_search_terms(message: str) -> List[str]:
    msg = (message or "").lower()
    terms: List[str] = []
    quoted = re.findall(r'"([^"]{2,60})"|(?<!\w)' + r"'([^']{2,60})'(?!\w)", message or "")
    quoted = [double or single for double, single in quoted]
    terms.extend(q.strip() for q in quoted if q.strip())

    for pattern in (
        r"\b(?:called|titled|named|with|at|about)\s+([a-z0-9][a-z0-9 '&.-]{2,60})",
        r"\b(?:search|find|look for)\s+([a-z0-9][a-z0-9 '&.-]{2,60})",
    ):
        for match in re.finditer(pattern, msg):
            phrase = re.split(
                r"\b(?:today|tomorrow|this week|next week|this month|next month|on|from|to)\b",
                match.group(1),
                maxsplit=1,
            )[0].strip(" ?.,")
            if (
                phrase
                and phrase not in _STOPWORDS
                and not _is_time_phrase(phrase)
                and not _is_temporal_search_phrase(phrase)
            ):
                terms.append(phrase)

    deduped: List[str] = []
    for term in terms:
        cleaned = term.strip().lower()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped[:5]


def _is_time_phrase(phrase: str) -> bool:
    cleaned = (phrase or "").strip().lower()
    return bool(re.fullmatch(
        r"(?:[01]?\d|2[0-3])(?::[0-5]\d|\.[0-5]\d)\s*(?:am|pm)?"
        r"|(?:1[0-2]|0?[1-9])\s*(?:am|pm)"
        r"|(?:[01]?\d|2[0-3])",
        cleaned,
    ))


def _is_temporal_search_phrase(phrase: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (phrase or "").strip().lower())
    return cleaned in _TEMPORAL_SEARCH_PHRASES


def _row_to_event(row) -> Dict:
    event_id, calendar_id, title, start_time, end_time, all_day, location, description, synced_at = row
    return {
        "event_id": event_id,
        "calendar_id": calendar_id,
        "title": title or "(untitled)",
        "start_time": start_time,
        "end_time": end_time,
        "all_day": bool(all_day),
        "location": location or "",
        "description": description or "",
        "synced_at": synced_at,
        "source": "samsung",
    }


def query_events(
    start: datetime,
    end: datetime,
    search_terms: Optional[List[str]] = None,
    limit: int = MAX_PROMPT_EVENTS,
    raise_on_error: bool = False,
) -> List[Dict]:
    """Fetch Samsung-synced events overlapping a UTC-normalised window."""
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            params = {
                "start": _to_utc(start),
                "end": _to_utc(end),
                "limit": limit,
            }
            search_sql = ""
            if search_terms:
                clauses = []
                for idx, term in enumerate(search_terms[:5]):
                    key = f"term_{idx}"
                    params[key] = f"%{term}%"
                    clauses.append(
                        f"(title ILIKE %({key})s OR location ILIKE %({key})s "
                        f"OR description ILIKE %({key})s)"
                    )
                search_sql = " AND (" + " OR ".join(clauses) + ")"

            cur.execute(f"""
                SELECT event_id, calendar_id, title, start_time, end_time,
                       all_day, location, description, synced_at
                FROM samsung_calendar_events
                WHERE start_time < %(end)s
                  AND (
                      COALESCE(end_time, start_time) > %(start)s
                      OR (
                          COALESCE(end_time, start_time) = start_time
                          AND start_time >= %(start)s
                      )
                  )
                  {search_sql}
                ORDER BY start_time ASC
                LIMIT %(limit)s
            """, params)
            return [_row_to_event(row) for row in cur.fetchall()]
    except psycopg2_errors.UndefinedTable:
        if raise_on_error:
            raise
        return []
    except Exception as e:
        record_run_event(
            event_type="samsung_calendar_query_failed",
            severity=EventSeverity.WARNING,
            subsystem="calendar.samsung.query",
            message="Samsung calendar query failed",
            error_class=type(e).__name__,
            error_message=str(e)[:300],
            metadata={"limit": limit, "has_search_terms": bool(search_terms)},
        )
        if raise_on_error:
            raise
        return []
    finally:
        if conn:
            conn.close()


def _format_time_range(event: Dict) -> str:
    start = event["start_time"].astimezone(UK_TZ)
    end = event["end_time"].astimezone(UK_TZ) if event.get("end_time") else None
    if event.get("all_day"):
        return start.strftime("%a %d %b") + " all day"
    if end and end.date() == start.date():
        return f"{start.strftime('%a %d %b %H:%M')}-{end.strftime('%H:%M')}"
    if end:
        return f"{start.strftime('%a %d %b %H:%M')} to {end.strftime('%a %d %b %H:%M')}"
    return start.strftime("%a %d %b %H:%M")


def format_events_for_prompt(events: List[Dict], window_label: str, search_terms: Optional[List[str]] = None) -> str:
    if not events:
        search_note = f" matching {', '.join(search_terms)}" if search_terms else ""
        return (
            "[SAMSUNG CALENDAR]\n"
            f"No matching stored Samsung calendar entries are visible for {window_label}{search_note}. "
            "Do not fabricate calendar entries."
        )

    lines = [
        "[SAMSUNG CALENDAR]",
        f"Synced device-calendar entries for {window_label}. Use these as the primary calendar source.",
    ]
    for event in events[:MAX_PROMPT_EVENTS]:
        line = f"- {_format_time_range(event)}: {event['title']}"
        if event.get("location"):
            line += f" @ {event['location']}"
        lines.append(line)
    if len(events) >= MAX_PROMPT_EVENTS:
        lines.append(f"Only the first {MAX_PROMPT_EVENTS} matching events are shown.")
    lines.append("If the answer needs entries not shown here, say they are not visible in the synced calendar context.")
    return "\n".join(lines)


async def get_calendar_context_for_message(message: str) -> str:
    """Return a bounded Samsung calendar prompt block for calendar-shaped chat."""
    if not is_calendar_query(message):
        return ""
    start, end, label = infer_query_window(message)
    terms = _extract_search_terms(message)
    events = await asyncio.to_thread(
        query_events,
        start,
        end,
        search_terms=terms or None,
        raise_on_error=True,
    )
    return format_events_for_prompt(events, label, terms)


async def read_calendar_for_message(message: str) -> str:
    """Deterministic command-parser calendar read, Samsung-first."""
    context = await get_calendar_context_for_message(message)
    if not context:
        start, end, label = infer_query_window(message or "today")
        events = query_events(start, end, raise_on_error=True)
        context = format_events_for_prompt(events, label)
    return context.replace("[SAMSUNG CALENDAR]\n", "", 1)


def get_calendar_diagnostics() -> Dict:
    """Return high-signal Samsung calendar diagnostics without dumping the table."""
    conn = None
    empty = {
        "ok": True,
        "source": "samsung",
        "total_stored_events": 0,
        "future_stored_events": 0,
        "earliest_event": None,
        "latest_event": None,
        "latest_synced_at": None,
        "next_10_upcoming_events": [],
    }
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE start_time >= NOW()),
                       MIN(start_time),
                       MAX(start_time),
                       MAX(synced_at)
                FROM samsung_calendar_events
            """)
            total, future, earliest, latest, latest_synced = cur.fetchone()
            cur.execute("""
                SELECT event_id, calendar_id, title, start_time, end_time,
                       all_day, location, description, synced_at
                FROM samsung_calendar_events
                WHERE start_time >= NOW()
                ORDER BY start_time ASC
                LIMIT 10
            """)
            upcoming = [_row_to_event(row) for row in cur.fetchall()]

        def iso(value):
            return value.isoformat() if value else None

        return {
            "ok": True,
            "source": "samsung",
            "total_stored_events": total,
            "future_stored_events": future,
            "earliest_event": iso(earliest),
            "latest_event": iso(latest),
            "latest_synced_at": iso(latest_synced),
            "next_10_upcoming_events": [
                {
                    "title": event["title"],
                    "start_time": iso(event["start_time"]),
                    "end_time": iso(event["end_time"]),
                    "all_day": event["all_day"],
                    "location": event["location"],
                    "source": "samsung",
                }
                for event in upcoming
            ],
        }
    except psycopg2_errors.UndefinedTable:
        return empty
    except Exception as e:
        record_run_event(
            event_type="samsung_calendar_diagnostics_failed",
            severity=EventSeverity.WARNING,
            subsystem="calendar.samsung.diagnostics",
            message="Samsung calendar diagnostics failed",
            error_class=type(e).__name__,
            error_message=str(e)[:300],
        )
        return {"ok": False, "source": "samsung", "error": "samsung_calendar_diagnostics_failed"}
    finally:
        if conn:
            conn.close()
