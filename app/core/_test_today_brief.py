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
            {
                "pending_id": "p1",
                "display_title": "gmail_send: send",
                "display_summary": "Send email",
                "risk_level": "high",
                "status": "awaiting",
            }
        ]
        fake_approval_module.build_pending_approval_summary = lambda approvals: {
            "count": len(approvals),
            "has_pending": bool(approvals),
            "high_risk_count": 1,
            "risk_counts": {"high": 1, "medium": 0, "low": 0, "unknown": 0},
            "cards": [{
                "pending_id": "p1",
                "title": "gmail_send: send",
                "summary": "Send email",
                "risk_level": "high",
            }],
        }

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
        self.assertEqual(result["attention"]["approvals"]["high_risk_count"], 1)
        self.assertEqual(result["approval_cards"][0]["title"], "gmail_send: send")
        self.assertEqual(result["health_flags"][0]["code"], "high_risk_approvals")
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

    def test_health_flags_surface_degraded_daily_signals(self):
        from app.core.today_brief import _build_health_flags

        flags = _build_health_flags(
            email_digest={"ok": False, "error": "Gmail failed"},
            recent_activity=[{"status": "failed", "summary": "Briefing failed"}],
            codebase_stats={"error": "database unavailable"},
            approval_summary={"high_risk_count": 2},
        )

        codes = [flag["code"] for flag in flags]
        self.assertEqual(codes, [
            "gmail_connection",
            "high_risk_approvals",
            "codebase_sync_error",
            "recent_run_failed",
        ])


if __name__ == "__main__":
    unittest.main()
