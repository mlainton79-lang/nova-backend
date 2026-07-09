import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CodebaseSyncTests(unittest.TestCase):
    def test_store_files_uses_savepoint_and_continues_after_file_failure(self):
        from app.core import codebase_sync

        executed = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed.append(sql.strip().split()[0].upper())
                if params and len(params) >= 2 and params[1] == "bad.py":
                    raise RuntimeError("bad row")

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
        with mock.patch.object(codebase_sync, "get_conn", return_value=conn):
            result = codebase_sync.store_files(
                "frontend",
                {
                    "good.kt": "class Good",
                    "bad.py": "def broken(): pass",
                    "later.kt": "class Later",
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stored"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["failed_paths"], ["bad.py"])
        self.assertTrue(conn.committed)
        self.assertGreaterEqual(executed.count("SAVEPOINT"), 3)
        self.assertIn("ROLLBACK", executed)


if __name__ == "__main__":
    unittest.main()
