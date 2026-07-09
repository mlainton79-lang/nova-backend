import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class DailyReviewTests(unittest.TestCase):
    def test_recent_run_ledger_activity_filters_today_and_counts_statuses(self):
        from app.core import daily_review

        now = datetime.now()
        fake_run_ledger = types.ModuleType("app.core.run_ledger")
        fake_run_ledger.recent_runs = lambda limit=20: [
            {
                "id": 1,
                "action_type": "briefing",
                "summary": "Built today brief",
                "status": "success",
                "trace_id": "t1",
                "created_at": now,
            },
            {
                "id": 2,
                "action_type": "sync",
                "summary": "Sync failed",
                "status": "failed",
                "trace_id": "t2",
                "created_at": now,
            },
            {
                "id": 3,
                "action_type": "old",
                "summary": "Yesterday",
                "status": "success",
                "trace_id": "t3",
                "created_at": now - timedelta(days=1),
            },
        ]

        with mock.patch.dict(sys.modules, {"app.core.run_ledger": fake_run_ledger}):
            result = daily_review._recent_run_ledger_activity()

        self.assertEqual(result["counts"]["success"], 1)
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertEqual(len(result["items"]), 2)

    def test_review_actions_prioritise_failed_runs_and_urgent_items(self):
        from app.core.daily_review import _build_review_actions

        actions = _build_review_actions({
            "run_ledger": {
                "counts": {"failed": 1, "awaiting_approval": 2},
            },
            "emails_by_urgency": {"urgent": 3},
            "alerts": [{"priority": "urgent", "title": "Check this"}],
        })

        self.assertEqual(actions, [
            "Review 1 failed Nova run(s).",
            "Pick up 2 run(s) awaiting approval.",
            "Carry forward 3 urgent email(s).",
            "Resolve 1 urgent alert(s).",
        ])

    def test_fallback_review_mentions_run_ledger(self):
        from app.core.daily_review import _fallback_review

        text = _fallback_review({
            "run_ledger": {"counts": {"success": 2, "failed": 0}},
        })

        self.assertIn("2 Nova run(s) completed", text)


if __name__ == "__main__":
    unittest.main()
