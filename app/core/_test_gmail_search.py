import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class GmailSearchTests(unittest.TestCase):
    def test_detailed_search_surfaces_account_errors(self):
        from app.core import gmail_service

        async def fake_list(account, **_kwargs):
            if account == "bad@example.com":
                raise gmail_service.GmailApiError(400, "Precondition check failed")
            return [{"account": account, "date": "Mon, 01 Jan 2026", "subject": "ok"}]

        with mock.patch.object(gmail_service, "get_all_accounts", return_value=["good@example.com", "bad@example.com"]), \
             mock.patch.object(gmail_service, "list_emails", side_effect=fake_list):
            result = asyncio.run(gmail_service.search_all_accounts_detailed("is:unread"))

        self.assertEqual(result["accounts_checked"], 2)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["errors"][0]["account"], "bad@example.com")
        self.assertIn("Gmail API 400", result["errors"][0]["error"])

    def test_legacy_search_returns_results_only(self):
        from app.core import gmail_service

        async def fake_detailed(*_args, **_kwargs):
            return {"results": [{"subject": "ok"}], "errors": [{"account": "bad"}]}

        with mock.patch.object(gmail_service, "search_all_accounts_detailed", side_effect=fake_detailed):
            result = asyncio.run(gmail_service.search_all_accounts("anything"))

        self.assertEqual(result, [{"subject": "ok"}])


if __name__ == "__main__":
    unittest.main()
