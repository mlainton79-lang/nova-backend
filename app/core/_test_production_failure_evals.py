import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ProductionFailureEvalCandidateTests(unittest.TestCase):
    def test_normalise_failure_event_redacts_email_and_token(self):
        from app.core.production_failure_evals import normalise_failure_event

        event = normalise_failure_event({
            "id": 7,
            "source_service": "web",
            "event_type": "gmail_refresh_failed",
            "severity": "error",
            "subsystem": "gmail.refresh",
            "message": "failed for user@example.com",
            "error_class": "HTTPError",
            "error_message": "token sk-abcdefghijklmnopqrstuvwxyz123456 expired",
            "metadata": {"account": "person@example.com", "request_id": "abc"},
            "created_at": datetime(2026, 7, 9, tzinfo=timezone.utc),
        })

        rendered = str(event)
        self.assertNotIn("user@example.com", rendered)
        self.assertNotIn("person@example.com", rendered)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", rendered)
        self.assertIn("[redacted-email]", rendered)
        self.assertIn("[redacted-token]", rendered)

    def test_candidate_names_subsystem_and_requires_review(self):
        from app.core.production_failure_evals import build_eval_candidate_from_event

        candidate = build_eval_candidate_from_event({
            "id": 42,
            "event_type": "triage_digest_failed",
            "severity": "warning",
            "subsystem": "email.triage",
            "message": "Gmail fetch failed",
            "error_class": "BadRequest",
            "error_message": "400 Bad Request",
        })

        self.assertEqual(candidate["id"], "prod.email_triage.triage_digest_failed.42")
        self.assertEqual(candidate["proposed_test"]["category"], "production_failure.email_triage")
        self.assertIn("email.triage", candidate["proposed_test"]["message"])
        self.assertIn("everything is fine", candidate["proposed_test"]["must_not_contain"])
        self.assertTrue(candidate["review_required"])

    def test_build_eval_candidates_deduplicates_same_failure_shape(self):
        from app.core.production_failure_evals import build_eval_candidates

        events = [
            {
                "id": 1,
                "event_type": "failed",
                "severity": "error",
                "subsystem": "memory.semantic",
                "error_class": "Timeout",
                "error_message": "timeout",
            },
            {
                "id": 2,
                "event_type": "failed",
                "severity": "error",
                "subsystem": "memory.semantic",
                "error_class": "Timeout",
                "error_message": "timeout",
            },
        ]

        self.assertEqual(len(build_eval_candidates(events)), 1)


if __name__ == "__main__":
    unittest.main()
