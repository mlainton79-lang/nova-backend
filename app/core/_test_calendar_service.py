#!/usr/bin/env python3
"""Unit tests for app.core.calendar_service Samsung read path.

Invokable directly, no pytest dependency:
    /usr/bin/python3 app/core/_test_calendar_service.py
"""
import os
import sys
import types
import unittest
from datetime import datetime
from importlib.util import find_spec

def _safe_find_spec(name: str):
    try:
        return find_spec(name)
    except ValueError:
        return None

from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

if _safe_find_spec("psycopg2") is None:
    psycopg2_stub = types.ModuleType("psycopg2")
    psycopg2_stub.errors = types.SimpleNamespace(UndefinedTable=type("UndefinedTable", (Exception,), {}))
    sys.modules["psycopg2"] = psycopg2_stub
    sys.modules["psycopg2.errors"] = psycopg2_stub.errors

from app.core import calendar_service  # noqa: E402


class CalendarServiceSamsungTests(unittest.TestCase):
    def test_grounded_samsung_schedule_reports_unavailable_when_fetch_fails(self):
        now = datetime(2026, 6, 30, 12, 0, tzinfo=ZoneInfo("Europe/London"))

        with patch("app.core.samsung_calendar.get_events_between", return_value=None):
            result = calendar_service.get_grounded_samsung_todays_schedule(now)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_fetched_event_records")
        self.assertIn("unavailable", result["schedule"])

    def test_grounded_samsung_schedule_allows_empty_fetch(self):
        now = datetime(2026, 6, 30, 12, 0, tzinfo=ZoneInfo("Europe/London"))

        with patch("app.core.samsung_calendar.get_events_between", return_value=[]):
            result = calendar_service.get_grounded_samsung_todays_schedule(now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["reason"], "no_events_in_requested_range")
        self.assertEqual(result["schedule"], "Nothing in the Samsung calendar today.")

    def test_grounded_samsung_schedule_formats_only_fetched_events(self):
        now = datetime(2026, 6, 30, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        events = [
            {
                "id": "cal1:evt1",
                "event_id": "cal1:evt1",
                "title": "Dentist",
                "start": "2026-06-30T09:00:00+01:00",
                "end": "2026-06-30T10:00:00+01:00",
                "all_day": False,
                "location": "Town",
                "source": "samsung_calendar",
            }
        ]

        with patch("app.core.samsung_calendar.get_events_between", return_value=events):
            result = calendar_service.get_grounded_samsung_todays_schedule(now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "fetched_records_available")
        self.assertEqual(result["events"], events)
        self.assertIn("09:00 - Dentist (Town)", result["schedule"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
