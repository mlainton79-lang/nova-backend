import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class DailyLoopQualityTests(unittest.TestCase):
    def test_today_brief_payload_scores_required_shape(self):
        from app.core.daily_loop_quality import evaluate_today_brief_payload

        result = evaluate_today_brief_payload({
            "briefing": "A useful day.",
            "next_actions": ["Review approvals."],
            "health_flags": [],
            "email_attention": {"urgent": [], "needs_reply": [], "errors": []},
            "approval_cards": [],
        })

        self.assertEqual(result["surface"], "today_brief")
        self.assertEqual(result["score"], 1.0)

    def test_daily_review_payload_fails_missing_run_ledger(self):
        from app.core.daily_loop_quality import evaluate_daily_review_payload

        result = evaluate_daily_review_payload({
            "review": "Quiet one today.",
            "follow_up_actions": ["No follow-up action surfaced."],
            "signals": {},
        })

        self.assertLess(result["score"], 1.0)
        failed = [check["name"] for check in result["checks"] if not check["passed"]]
        self.assertEqual(failed, ["has_run_ledger_signal"])

    def test_combined_quality_marks_partial_failures_needs_attention(self):
        from app.core.daily_loop_quality import combine_daily_loop_quality

        result = combine_daily_loop_quality([
            {"passed": 2, "total": 2, "surface": "ok"},
            {"passed": 1, "total": 2, "surface": "partial"},
        ])

        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["status"], "needs_attention")


if __name__ == "__main__":
    unittest.main()
