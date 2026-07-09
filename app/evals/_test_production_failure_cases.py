import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class ProductionFailureCasePromotionTests(unittest.TestCase):
    def test_sidecar_json_exists_and_is_loaded(self):
        from app.evals import test_cases

        sidecar = Path(test_cases.__file__).with_name("production_failure_cases.json")
        self.assertTrue(sidecar.exists())
        self.assertIsInstance(test_cases._load_production_failure_cases(), list)

    def test_promote_candidates_merges_by_id(self):
        from tools.promote_failure_candidates import promote_candidates

        result = promote_candidates(
            [
                {
                    "id": "prod.email.fetch.1",
                    "source_event_id": 1,
                    "evidence": "severity=error; subsystem=email",
                    "proposed_test": {
                        "message": "Production signal: email failed.",
                        "must_not_contain": ["all caught up"],
                        "expected_behaviour": "Name the failure and next action.",
                        "category": "production_failure.email",
                        "max_words": 80,
                    },
                }
            ],
            [
                {
                    "id": "prod.email.fetch.1",
                    "message": "old",
                    "expected_behaviour": "old",
                    "category": "production_failure.email",
                },
                {
                    "id": "prod.memory.write.2",
                    "message": "Memory failed.",
                    "expected_behaviour": "Name memory failure.",
                    "category": "production_failure.memory",
                },
            ],
        )

        by_id = {case["id"]: case for case in result}
        self.assertEqual(len(result), 2)
        self.assertEqual(by_id["prod.email.fetch.1"]["message"], "Production signal: email failed.")
        self.assertEqual(by_id["prod.email.fetch.1"]["source_event_id"], 1)
        self.assertIn("production_evidence", by_id["prod.email.fetch.1"])

    def test_promote_candidates_rejects_missing_required_fields(self):
        from tools.promote_failure_candidates import promote_candidates

        with self.assertRaises(ValueError):
            promote_candidates(
                [{"id": "bad", "proposed_test": {"message": "missing expected"}}],
                [],
            )


if __name__ == "__main__":
    unittest.main()
