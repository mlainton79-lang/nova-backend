import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class FormatGmailSearchBlockTests(unittest.TestCase):
    def _fmt(self, detailed, limit=8):
        from app.core.gmail_service import format_gmail_search_block

        return format_gmail_search_block(detailed, limit=limit)

    def test_results_and_errors_both_rendered(self):
        block = self._fmt({
            "results": [{"from": "Vinted <no-reply@vinted.co.uk>", "subject": "Item favourited", "date": "Sat, 18 Jul 2026 10:00", "snippet": "Your item"}],
            "errors": [{"account": "mlainton78@gmail.com", "error": "GmailApiError: needs_reauth"}],
            "accounts_checked": 4,
        })
        self.assertIn("[GMAIL SEARCH]", block)
        self.assertIn("Vinted — Item favourited", block)
        self.assertIn("ACCOUNTS NOT READABLE", block)
        self.assertIn("mlainton78@gmail.com: GmailApiError: needs_reauth", block)
        self.assertIn("Never guess or invent", block)

    def test_no_results_no_errors_says_no_matches_not_absence(self):
        block = self._fmt({"results": [], "errors": [], "accounts_checked": 4})
        self.assertIn("No matching emails found across 4 account(s)", block)
        self.assertNotIn("ACCOUNTS NOT READABLE", block)

    def test_errors_only_still_returns_block_naming_accounts(self):
        block = self._fmt({
            "results": [],
            "errors": [
                {"account": "a@x.com", "error": "TimeoutError"},
                {"account": "b@x.com", "error": "GmailApiError: 401"},
            ],
            "accounts_checked": 4,
        })
        self.assertIn("No matching emails found", block)
        self.assertIn("a@x.com: TimeoutError", block)
        self.assertIn("b@x.com: GmailApiError: 401", block)

    def test_limit_respected(self):
        results = [{"from": f"S{i} <s@x>", "subject": f"Sub{i}", "date": "", "snippet": ""} for i in range(10)]
        block = self._fmt({"results": results, "errors": [], "accounts_checked": 4}, limit=3)
        self.assertIn("Sub2", block)
        self.assertNotIn("Sub3", block)

    def test_missing_keys_fail_safe(self):
        block = self._fmt({})
        self.assertIn("[GMAIL SEARCH]", block)
        self.assertIn("across 0 account(s)", block)


class ListEmailsNeedsReauthContractTests(unittest.TestCase):
    def test_dead_token_raises_not_empty_list(self):
        import asyncio
        from unittest import mock

        from app.core import gmail_service

        async def _no_token(_email):
            return None

        with mock.patch.object(gmail_service, "refresh_access_token", _no_token):
            with self.assertRaises(gmail_service.GmailApiError) as ctx:
                asyncio.get_event_loop().run_until_complete(
                    gmail_service.list_emails("dead@example.com")
                )
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("needs_reauth", str(ctx.exception))
        self.assertIn("dead@example.com", str(ctx.exception))


class FetchPerAccountLiteralReauthTests(unittest.TestCase):
    """Codex P2 on 1ac45d2: literal per-account inbox request must surface
    Gmail-authoritative failures as an explicit unreadable-account block,
    not swallow to None (which fell through to the cross-account digest)."""

    def test_gmail_api_error_returns_explicit_unreadable_block(self):
        import asyncio
        from unittest import mock

        from app.core import gmail_service

        async def _raise(*_a, **_k):
            raise gmail_service.GmailApiError(
                401, "needs_reauth: token refresh returned no token for x@y.com"
            )

        with mock.patch.object(gmail_service, "get_all_accounts", return_value=["x@y.com"]), \
             mock.patch.object(gmail_service, "list_emails", new=_raise):
            block = asyncio.get_event_loop().run_until_complete(
                gmail_service.fetch_per_account_literal("last 5 emails in x@y.com")
            )
        self.assertIsNotNone(block)
        self.assertIn("[GMAIL: x@y.com]", block)
        self.assertIn("ACCOUNT NOT READABLE", block)
        self.assertIn("401", block)
        self.assertIn("Never guess or invent", block)

    def test_non_gmail_exception_still_falls_through_to_none(self):
        import asyncio
        from unittest import mock

        from app.core import gmail_service

        async def _timeout(*_a, **_k):
            raise TimeoutError("wire timeout")

        with mock.patch.object(gmail_service, "get_all_accounts", return_value=["x@y.com"]), \
             mock.patch.object(gmail_service, "list_emails", new=_timeout):
            result = asyncio.get_event_loop().run_until_complete(
                gmail_service.fetch_per_account_literal("last 5 emails in x@y.com")
            )
        self.assertIsNone(result)


class EndpointBlockContractTests(unittest.TestCase):
    """Source-level contracts, runnable even without fastapi installed."""

    def test_council_endpoint_uses_detailed_and_formatter(self):
        src = Path("app/api/v1/endpoints/council.py").read_text()
        self.assertIn("search_all_accounts_detailed", src)
        self.assertIn("format_gmail_search_block", src)
        self.assertNotIn("search_all_accounts(req.message", src)

    def test_chat_stream_endpoint_uses_detailed_and_formatter(self):
        src = Path("app/api/v1/endpoints/chat_stream.py").read_text()
        self.assertIn("search_all_accounts_detailed", src)
        self.assertIn("format_gmail_search_block", src)
        self.assertNotIn("search_all_accounts(request.message", src)


if __name__ == "__main__":
    unittest.main()
