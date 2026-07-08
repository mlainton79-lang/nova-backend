import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class RagInitTests(unittest.TestCase):
    def test_init_keeps_existing_matching_embedding_column(self):
        from app.core import rag

        original_get_conn = rag.get_conn
        executed = []

        class FakeCursor:
            def __init__(self):
                self._next_fetchone = None

            def execute(self, sql, *_args, **_kwargs):
                executed.append(sql)
                if "SELECT format_type" in sql:
                    self._next_fetchone = ("vector(3072)",)

            def fetchone(self):
                row = self._next_fetchone
                self._next_fetchone = None
                return row

            def close(self):
                return None

        class FakeConn:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                return None

            def rollback(self):
                return None

            def close(self):
                return None

        try:
            rag.get_conn = lambda: FakeConn()
            rag.init_rag_tables()
        finally:
            rag.get_conn = original_get_conn

        sql_text = "\n".join(executed)
        self.assertNotIn("DROP TABLE IF EXISTS case_chunks", sql_text)
        self.assertIn("embedding::halfvec(3072)", sql_text)


if __name__ == "__main__":
    unittest.main()
