import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CommandParserDailyReviewTests(unittest.TestCase):
    def test_daily_review_formatter_includes_useful_follow_ups(self):
        from app.core.command_parser import _format_daily_review_response

        text = _format_daily_review_response({
            "review": "Two useful things happened today.",
            "follow_up_actions": [
                "Review 1 failed Nova run(s).",
                "Carry forward 2 urgent email(s).",
            ],
        })

        self.assertIn("Two useful things happened today.", text)
        self.assertIn("Follow-up:", text)
        self.assertIn("- Review 1 failed Nova run(s).", text)
        self.assertIn("- Carry forward 2 urgent email(s).", text)

    def test_daily_review_formatter_hides_empty_follow_up_placeholder(self):
        from app.core.command_parser import _format_daily_review_response

        text = _format_daily_review_response({
            "review": "Quiet one today.",
            "follow_up_actions": ["No follow-up action surfaced."],
        })

        self.assertEqual(text, "Quiet one today.")


if __name__ == "__main__":
    unittest.main()
