import asyncio
import sys
import unittest
from datetime import datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class SelfRepairTests(unittest.TestCase):
    def test_startup_web_event_counts_as_autonomous_loop_heartbeat(self):
        from app.core import self_repair

        original_get_conn = self_repair.get_conn

        class FakeCursor:
            def __init__(self):
                self._next_fetchone = None

            def execute(self, sql, *_args, **_kwargs):
                if "FROM memories" in sql:
                    self._next_fetchone = (1,)
                elif "FROM semantic_memories" in sql:
                    self._next_fetchone = (1,)
                elif "FROM tony_eval_log" in sql:
                    self._next_fetchone = (0,)
                elif "FROM run_events" in sql:
                    self._next_fetchone = (datetime.now(),)
                elif "FROM gmail_accounts" in sql:
                    self._next_fetchone = (1,)
                else:
                    self._next_fetchone = (None,)

            def fetchone(self):
                row = self._next_fetchone
                self._next_fetchone = None
                return row

            def close(self):
                return None

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            def close(self):
                return None

        try:
            self_repair.get_conn = lambda: FakeConn()
            health = asyncio.run(self_repair.check_system_health())
        finally:
            self_repair.get_conn = original_get_conn

        self.assertEqual(health["overall"], "healthy")
        self.assertEqual(health["checks"]["autonomous_loop"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
