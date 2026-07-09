import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class EmailTriageListTests(unittest.TestCase):
    def test_list_needs_reply_items_maps_rows(self):
        from app.core import email_triage

        now = datetime(2026, 7, 9, 13, 0, tzinfo=timezone.utc)

        class FakeCursor:
            def __init__(self):
                self.params = None

            def execute(self, _sql, params=None):
                self.params = params

            def fetchall(self):
                return [(
                    "hash1", "msg1", "me@example.com", "Sender", "Subject",
                    "urgent", "admin", True, "Draft body", "Summary",
                    "reply", now,
                )]

            def close(self):
                return None

        class FakeConn:
            def __init__(self):
                self.cur = FakeCursor()

            def cursor(self):
                return self.cur

            def close(self):
                return None

        conn = FakeConn()
        with mock.patch.object(email_triage, "get_conn", return_value=conn):
            result = email_triage.list_triage_items("needs_reply", limit=200)

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(conn.cur.params, (50,))
        self.assertEqual(result["items"][0]["reply_draft"], "Draft body")
        self.assertEqual(result["items"][0]["triaged_at"], "2026-07-09T13:00:00+00:00")

    def test_unknown_kind_returns_error(self):
        from app.core.email_triage import list_triage_items

        result = list_triage_items("missing")

        self.assertFalse(result["ok"])
        self.assertIn("unknown triage kind", result["error"])


if __name__ == "__main__":
    unittest.main()
