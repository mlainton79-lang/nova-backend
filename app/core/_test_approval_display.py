import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ApprovalDisplayTests(unittest.TestCase):
    def test_display_fields_mark_destructive_or_external_caps_high_risk(self):
        from app.core.approval_lock import _approval_display_fields

        fields = _approval_display_fields(
            "gmail_send",
            {"step_summary": "Send the reviewed email", "action_type": "send"},
        )

        self.assertEqual(fields["display_summary"], "Send the reviewed email")
        self.assertEqual(fields["risk_level"], "high")
        self.assertIn("gmail_send", fields["display_title"])

    def test_display_fields_default_medium_for_unknown_safe_shape(self):
        from app.core.approval_lock import _approval_display_fields

        fields = _approval_display_fields("calendar_read", {})

        self.assertEqual(fields["display_summary"], "Approval required")
        self.assertEqual(fields["risk_level"], "medium")


if __name__ == "__main__":
    unittest.main()
