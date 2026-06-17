"""
Samsung calendar event store.

Persistent backing for events posted from the Android device's calendar.
proactive_scheduler.check_calendar_for_today() reads from this table;
this module is the writer.
"""
import os
import psycopg2
from typing import Dict, List


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


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
