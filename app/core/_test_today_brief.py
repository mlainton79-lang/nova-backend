import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class TodayBriefTests(unittest.TestCase):
    def test_today_brief_combines_attention_and_next_actions(self):
        from app.core import today_brief

        async def fake_intelligent():
            return {
                "ok": True,
                "briefing": "You have a couple of things to look at.",
                "state": {
                    "email_digest": {
                        "ok": True,
                        "count": 4,
                        "urgent_count": 1,
                        "needs_reply_count": 2,
                    }
                },
            }

        fake_intelligent_module = types.ModuleType("app.core.intelligent_briefing")
        fake_intelligent_module.get_intelligent_briefing = fake_intelligent

        fake_approval_module = types.ModuleType("app.core.approval_lock")
        fake_approval_module.list_active_pending_approvals = lambda limit=10: [
            {"pending_id": "p1", "step_summary": "Send email"}
        ]

        fake_run_ledger = types.ModuleType("app.core.run_ledger")
        fake_run_ledger.recent_runs = lambda limit=5: [
            {"id": 1, "status": "success", "summary": "Brief sent"}
        ]

        fake_codebase = types.ModuleType("app.core.codebase_sync")
        fake_codebase.get_codebase_stats = lambda: {
            "sources": [{"source": "frontend", "file_count": 10}]
        }

        with mock.patch.dict(sys.modules, {
            "app.core.intelligent_briefing": fake_intelligent_module,
            "app.core.approval_lock": fake_approval_module,
            "app.core.run_ledger": fake_run_ledger,
            "app.core.codebase_sync": fake_codebase,
        }):
            result = asyncio.run(today_brief.get_today_brief())

        self.assertTrue(result["ok"])
        self.assertEqual(result["attention"]["pending_approvals_count"], 1)
        self.assertEqual(result["attention"]["email"]["needs_reply_count"], 2)
        self.assertIn("Review 1 pending approval", result["next_actions"][0])
        self.assertTrue(any("email reply" in action for action in result["next_actions"]))

    def test_today_brief_defaults_to_no_urgent_action(self):
        from app.core.today_brief import _build_next_actions

        actions = _build_next_actions(
            approvals_count=0,
            email_digest={"ok": True, "count": 0},
            recent_activity=[],
            codebase_stats={"sources": [{"source": "backend"}]},
        )

        self.assertEqual(actions, ["No urgent action surfaced."])


if __name__ == "__main__":
    unittest.main()
