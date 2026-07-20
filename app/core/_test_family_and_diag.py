import asyncio
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class FamilyAgeTests(unittest.TestCase):
    def test_margot_first_birthday_is_twelve_months(self):
        from app.core.family import MARGOT_DOB, age_string

        self.assertEqual(age_string(MARGOT_DOB, date(2026, 7, 20)), "12 months")

    def test_margot_day_before_first_birthday_is_eleven_months(self):
        from app.core.family import MARGOT_DOB, age_string

        self.assertEqual(age_string(MARGOT_DOB, date(2026, 7, 19)), "11 months")

    def test_two_years_switches_to_years(self):
        from app.core.family import MARGOT_DOB, age_string

        self.assertEqual(age_string(MARGOT_DOB, date(2027, 7, 20)), "2")

    def test_amelia_age_across_birthday_boundary(self):
        from app.core.family import AMELIA_DOB, age_string

        self.assertEqual(age_string(AMELIA_DOB, date(2026, 3, 6)), "4")
        self.assertEqual(age_string(AMELIA_DOB, date(2026, 3, 7)), "5")

    def test_daughters_line_never_contains_stale_literals(self):
        from app.core.family import daughters_line

        line = daughters_line(date(2026, 7, 20))
        self.assertIn("Amelia (5)", line)
        self.assertIn("Margot (12 months)", line)

    def test_dad_loss_line_time_honest(self):
        from app.core.family import dad_loss_line

        self.assertIn("(very recently)", dad_loss_line(date(2026, 4, 20)))
        self.assertIn("(3 months ago)", dad_loss_line(date(2026, 7, 19)))
        self.assertIn("(1 year ago)", dad_loss_line(date(2027, 4, 10)))

    def test_family_dates_cover_all_six(self):
        from app.core.family import family_dates

        labels = {label for _, label in family_dates(2026)}
        self.assertEqual(len(labels), 6)
        self.assertIn("Margot's birthday", labels)
        self.assertIn("Anniversary of Dad's passing", labels)


class NoStaleLiteralsContractTests(unittest.TestCase):
    def test_emotional_intelligence_has_no_hardcoded_ages(self):
        src = Path("app/core/emotional_intelligence.py").read_text()
        self.assertNotIn("Margot (9 months)", src)
        self.assertNotIn("Amelia (5)", src)
        self.assertNotIn("(very recently)", src)
        self.assertIn("daughters_line()", src)
        self.assertIn("dad_loss_line()", src)

    def test_briefing_sources_dates_from_family_module(self):
        src = Path("app/core/intelligent_briefing.py").read_text()
        self.assertIn("family_dates(today.year)", src)
        self.assertNotIn('date(today.year, 7, 20), "Margot', src)


class DiagTokenTests(unittest.TestCase):
    def _call(self, header, dev="devtok", diag="diagtok"):
        with mock.patch("app.core.security.DEV_TOKEN", dev), \
             mock.patch("app.core.security.DIAG_TOKEN", diag):
            from app.core.security import verify_read_token

            return asyncio.get_event_loop().run_until_complete(
                verify_read_token(authorization=header)
            )

    def test_dev_token_accepted_with_dev_scope(self):
        self.assertEqual(self._call("Bearer devtok"), "dev")

    def test_diag_token_accepted_with_diag_scope(self):
        self.assertEqual(self._call("Bearer diagtok"), "diag")

    def test_wrong_token_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            self._call("Bearer nope")

    def test_diag_disabled_when_unset(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException):
            self._call("Bearer diagtok", diag=None)

    def test_dev_token_still_works_when_diag_unset(self):
        self.assertEqual(self._call("Bearer devtok", diag=None), "dev")

    def test_debug_handler_diag_branch_is_passive(self):
        src = Path("app/api/v1/endpoints/gmail.py").read_text()
        diag_branch = src.split('if scope == "diag":')[1].split("for account in accounts:")[0]
        self.assertNotIn("refresh_access_token(", diag_branch)
        self.assertNotIn("httpx", diag_branch)
        self.assertNotIn("UPDATE", diag_branch)
        self.assertIn("SELECT email, token_expiry", diag_branch)

    def test_debug_endpoint_uses_read_token_and_writes_do_not(self):
        src = Path("app/api/v1/endpoints/gmail.py").read_text()
        self.assertIn("verify_read_token", src)
        # Exactly one route uses the read token: /gmail/debug
        self.assertEqual(src.count("Depends(verify_read_token)"), 1)


if __name__ == "__main__":
    unittest.main()
