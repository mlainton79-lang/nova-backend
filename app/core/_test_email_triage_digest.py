import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class EmailTriageDigestTests(unittest.TestCase):
    def test_all_account_fetch_failures_do_not_report_all_caught_up(self):
        from app.core import email_triage

        async def fake_list_emails(*_args, **_kwargs):
            raise RuntimeError("gmail unavailable")

        with mock.patch("app.core.gmail_service.get_all_accounts", return_value=["a@example.com"]), \
             mock.patch("app.core.gmail_service.list_emails", side_effect=fake_list_emails):
            result = asyncio.run(email_triage.get_smart_digest())

        self.assertFalse(result["ok"])
        self.assertEqual(result["count"], 0)
        self.assertIn("Gmail fetch failed", result["error"])
        self.assertEqual(result["errors"][0]["account"], "a@example.com")

    def test_no_unread_with_successful_fetch_reports_all_caught_up(self):
        from app.core import email_triage

        async def fake_list_emails(*_args, **_kwargs):
            return []

        with mock.patch("app.core.gmail_service.get_all_accounts", return_value=["a@example.com"]), \
             mock.patch("app.core.gmail_service.list_emails", side_effect=fake_list_emails):
            result = asyncio.run(email_triage.get_smart_digest())

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)
        self.assertIn("All caught up", result["digest"])


if __name__ == "__main__":
    unittest.main()
