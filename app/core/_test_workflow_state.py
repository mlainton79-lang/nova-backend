import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class WorkflowStateTests(unittest.TestCase):
    def test_upsert_workflow_state_commits(self):
        from app.core import workflow_state

        class FakeCursor:
            def __init__(self):
                self.executed = []

            def execute(self, sql, params=None):
                self.executed.append((sql, params))

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
        with mock.patch.object(workflow_state, "init_workflow_state_table"), \
             mock.patch.object(workflow_state, "get_conn", return_value=conn):
            ok = workflow_state.upsert_workflow_state(
                workflow_id="wf-1",
                workflow_type="daily_loop",
                status="awaiting_approval",
                current_step="approval",
                summary="Waiting for Matthew",
                state={"pending_id": "redacted"},
            )

        self.assertTrue(ok)
        self.assertTrue(conn.committed)
        self.assertIn("INSERT INTO tony_workflow_state", conn.cur.executed[0][0])
        self.assertEqual(conn.cur.executed[0][1][0], "wf-1")

    def test_list_workflow_states_serialises_rows(self):
        from app.core import workflow_state

        now = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchall(self):
                return [(
                    "wf-1",
                    "daily_loop",
                    "paused",
                    "approval",
                    "Waiting",
                    {"step": 1},
                    now,
                    now,
                    None,
                    None,
                )]

            def close(self):
                return None

        class FakeConn:
            def cursor(self):
                return FakeCursor()

            def close(self):
                return None

        with mock.patch.object(workflow_state, "init_workflow_state_table"), \
             mock.patch.object(workflow_state, "get_conn", return_value=FakeConn()):
            rows = workflow_state.list_workflow_states(status="paused")

        self.assertEqual(rows[0]["workflow_id"], "wf-1")
        self.assertEqual(rows[0]["state"], {"step": 1})
        self.assertEqual(rows[0]["updated_at"], "2026-07-09T14:00:00+00:00")

    def test_list_paused_workflows_combines_pause_states(self):
        from app.core import workflow_state

        def fake_list(status=None, limit=20):
            return [{
                "workflow_id": f"{status}-1",
                "status": status,
                "updated_at": "2026-07-09T14:00:00+00:00" if status == "awaiting_approval" else "2026-07-09T13:00:00+00:00",
            }]

        with mock.patch.object(workflow_state, "list_workflow_states", side_effect=fake_list):
            rows = workflow_state.list_paused_workflows()

        self.assertEqual([row["workflow_id"] for row in rows], [
            "awaiting_approval-1",
            "paused-1",
        ])


if __name__ == "__main__":
    unittest.main()
