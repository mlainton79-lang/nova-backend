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

    def test_pending_summary_builds_compact_cards_and_counts_risk(self):
        from app.core.approval_lock import build_pending_approval_summary

        summary = build_pending_approval_summary([
            {
                "pending_id": "p1",
                "capability_key": "gmail_send",
                "display_title": "gmail_send: send",
                "display_summary": "Send reviewed email",
                "risk_level": "high",
                "status": "awaiting",
                "expires_at": "2026-07-09T10:00:00Z",
                "action_snapshot": {"request_body": "[REDACTED]"},
            },
            {
                "pending_id": "p2",
                "capability_key": "calendar_read",
                "display_title": "calendar_read: inspect",
                "display_summary": "Review calendar context",
                "risk_level": "medium",
                "status": "awaiting",
            },
        ])

        self.assertEqual(summary["count"], 2)
        self.assertTrue(summary["has_pending"])
        self.assertEqual(summary["high_risk_count"], 1)
        self.assertEqual(summary["risk_counts"]["medium"], 1)
        self.assertEqual(summary["cards"][0]["title"], "gmail_send: send")
        self.assertNotIn("action_snapshot", summary["cards"][0])


if __name__ == "__main__":
    unittest.main()
