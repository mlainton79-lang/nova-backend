import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CommandParserDailyReviewTests(unittest.TestCase):
    def test_today_brief_command_detects_now_phrase(self):
        from app.core.command_parser import detect_command

        command = detect_command("what can we do now then?")

        self.assertIsNotNone(command)
        self.assertEqual(command["command"], "today_brief")

    def test_today_brief_formatter_includes_next_actions_and_flags(self):
        from app.core.command_parser import _format_today_brief_response

        text = _format_today_brief_response({
            "briefing": "You have a couple of things to look at.",
            "next_actions": [
                "Review 1 pending approval(s).",
                "Review 2 email reply draft(s).",
            ],
            "health_flags": [
                {"message": "Gmail triage has connection errors."},
            ],
        })

        self.assertIn("You have a couple of things to look at.", text)
        self.assertIn("Next:", text)
        self.assertIn("- Review 1 pending approval(s).", text)
        self.assertIn("Flags:", text)
        self.assertIn("- Gmail triage has connection errors.", text)

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
