import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class RunLedgerTests(unittest.TestCase):
    def test_record_run_returns_inserted_id_and_commits(self):
        from app.core import run_ledger

        class FakeCursor:
            def __init__(self):
                self.executed = []

            def execute(self, sql, params=None):
                self.executed.append((sql, params))

            def fetchone(self):
                return [42]

            def close(self):
                return None

        class FakeConn:
            def __init__(self):
                self.cur = FakeCursor()
                self.committed = False

            def cursor(self):
                return self.cur

            def commit(self):
                self.committed = True

            def close(self):
                return None

        conn = FakeConn()
        with mock.patch.object(run_ledger, "init_run_ledger_table"), \
             mock.patch.object(run_ledger, "get_conn", return_value=conn):
            row_id = run_ledger.record_run(
                "scheduled_brief",
                trigger="test",
                summary="Generated brief",
                status="success",
                trace_id="nova-test",
                metadata={"type": "morning"},
            )

        self.assertEqual(row_id, 42)
        self.assertTrue(conn.committed)
        self.assertIn("INSERT INTO tony_run_ledger", conn.cur.executed[0][0])

    def test_recent_runs_serialises_datetimes(self):
        from app.core import run_ledger

        now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchall(self):
                return [
                    (
                        1,
                        "scheduled_brief",
                        "cron",
                        "Morning brief",
                        "success",
                        "ok",
                        "nova-test",
                        now,
                        None,
                        {"type": "morning"},
                    )
                ]

            def close(self):
                return None

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            def close(self):
                return None

        with mock.patch.object(run_ledger, "init_run_ledger_table"), \
             mock.patch.object(run_ledger, "get_conn", return_value=FakeConn()):
            rows = run_ledger.recent_runs(limit=1)

        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[0]["created_at"], "2026-07-09T12:00:00+00:00")
        self.assertEqual(rows[0]["metadata"], {"type": "morning"})


if __name__ == "__main__":
    unittest.main()
