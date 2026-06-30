#!/usr/bin/env python3
"""Unit tests for app.core.samsung_calendar.

Invokable directly, no pytest dependency:
    /usr/bin/python3 app/core/_test_samsung_calendar.py
"""
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from importlib.util import find_spec

def _safe_find_spec(name: str):
    try:
        return find_spec(name)
    except ValueError:
        return None

from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

if _safe_find_spec("psycopg2") is None:
    psycopg2_stub = types.ModuleType("psycopg2")
    psycopg2_stub.errors = types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}))
    sys.modules["psycopg2"] = psycopg2_stub
    sys.modules["psycopg2.errors"] = psycopg2_stub.errors

from app.core import samsung_calendar  # noqa: E402


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class SamsungCalendarReadTests(unittest.TestCase):
    def test_get_events_between_returns_normalised_rows(self):
        start = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        row = (
            "evt1",
            "cal1",
            "Dentist",
            datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 6, 30, 10, 0, tzinfo=timezone.utc),
            False,
            "Town",
            None,
            datetime(2026, 6, 29, 20, 0, tzinfo=timezone.utc),
        )
        conn = _FakeConn([row])

        with patch.object(samsung_calendar, "get_conn", return_value=conn):
            events = samsung_calendar.get_events_between(start, end)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_id"], "cal1:evt1")
        self.assertEqual(events[0]["samsung_event_id"], "evt1")
        self.assertEqual(events[0]["title"], "Dentist")
        self.assertEqual(events[0]["location"], "Town")
        self.assertTrue(conn.autocommit)
        self.assertTrue(conn.closed)

    def test_get_events_between_invalid_range_fails_closed_without_db(self):
        end = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc)
        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

        with patch.object(samsung_calendar, "get_conn") as get_conn:
            events = samsung_calendar.get_events_between(start, end)

        self.assertIsNone(events)
        get_conn.assert_not_called()

    def test_get_read_status_returns_count_and_latest_sync_only(self):
        synced_at = datetime(2026, 6, 30, 8, 15, tzinfo=timezone.utc)
        conn = _FakeConn([(12, synced_at)])

        with patch.object(samsung_calendar, "get_conn", return_value=conn):
            status = samsung_calendar.get_read_status()

        self.assertEqual(status["ok"], True)
        self.assertEqual(status["event_count"], 12)
        self.assertEqual(status["latest_synced_at"], synced_at.isoformat())
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
