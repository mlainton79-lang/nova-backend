import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class IntelligentBriefingTests(unittest.TestCase):
    def test_fallback_mentions_email_digest_when_cache_empty(self):
        from app.core.intelligent_briefing import _fallback_briefing

        text = _fallback_briefing({
            "alerts": [],
            "emails": [],
            "email_digest": {"ok": True, "count": 3},
            "calendar": [],
            "family_dates": [],
        })

        self.assertIn("3 unread email", text)

    def test_fallback_mentions_email_triage_failure(self):
        from app.core.intelligent_briefing import _fallback_briefing

        text = _fallback_briefing({
            "alerts": [],
            "emails": [],
            "email_digest": {"ok": False, "error": "Gmail failed"},
            "calendar": [],
            "family_dates": [],
        })

        self.assertIn("Email triage unavailable", text)


if __name__ == "__main__":
    unittest.main()
