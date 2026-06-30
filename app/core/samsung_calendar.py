"""
Samsung calendar event store.

Persistent backing for events posted from the Android device's calendar.
proactive_scheduler.check_calendar_for_today() reads from this table;
this module is the writer plus safe local read helpers.
"""
import os
from datetime import datetime
from typing import Dict, List, Optional, Sequence

import psycopg2
from psycopg2 import errors as psycopg2_errors

from app.observability import EVENT_TYPES, EventSeverity, record_run_event


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        sslmode="require",
        connect_timeout=10,
    )


def _record_read_failure(operation: str, e: Exception) -> None:
    record_run_event(
        event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
        severity=EventSeverity.WARNING,
        subsystem="api.calendar.samsung",
        message=f"samsung calendar {operation} failed",
        error_class=type(e).__name__,
        error_message=str(e)[:300],
    )


def _iso_or_none(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _row_to_event(row: Sequence) -> Dict:
    (
        event_id,
        calendar_id,
        title,
        start_time,
        end_time,
        all_day,
        location,
        description,
        synced_at,
    ) = row
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


def init_samsung_calendar_table():
    """Create samsung_calendar_events if needed."""
    try:
        conn = get_conn()
        cur = conn.cursor()
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
        conn.commit()
        cur.close()
        conn.close()
        print("[SAMSUNG_CAL] Table initialised")
    except Exception as e:
        print(f"[SAMSUNG_CAL] Init failed: {e}")


def get_events_between(start_time: datetime, end_time: datetime, limit: int = 50) -> Optional[List[Dict]]:
    """
    Read Samsung calendar events in [start_time, end_time).

    Returns None on read failure so callers can distinguish "no fetched
    records" from a successful empty result. This helper never mutates
    calendar items.
    """
    if not start_time or not end_time or start_time >= end_time:
        return None

    safe_limit = max(1, min(int(limit or 50), 200))
    try:
        conn = get_conn()
        try:
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
                return [_row_to_event(row) for row in cur.fetchall()]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except psycopg2_errors.UndefinedTable:
        return None
    except Exception as e:
        _record_read_failure("read", e)
        return None


def get_read_status() -> Dict:
    """Return local Samsung calendar read status without exposing event data."""
    try:
        conn = get_conn()
        try:
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
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except psycopg2_errors.UndefinedTable:
        return {"ok": False, "event_count": 0, "latest_synced_at": None}
    except Exception as e:
        _record_read_failure("status", e)
        return {"ok": False, "event_count": 0, "latest_synced_at": None}


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
