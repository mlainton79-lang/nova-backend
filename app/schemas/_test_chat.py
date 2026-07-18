import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CouncilResponseSchemaTests(unittest.TestCase):
    def test_accepts_and_preserves_council_health_dict(self):
        from app.schemas.chat import CouncilResponse

        health = {
            "seats": 3,
            "responded": 2,
            "chair": "claude",
            "dark": [{"name": "gemini", "error_class": "DisabledViaEnv"}],
        }
        resp = CouncilResponse(
            ok=True,
            provider="council",
            reply="hi",
            council_health=health,
        )
        self.assertEqual(resp.council_health, health)

        dumped = resp.model_dump() if hasattr(resp, "model_dump") else resp.dict()
        self.assertEqual(dumped["council_health"], health)

    def test_council_health_defaults_to_none_when_absent(self):
        from app.schemas.chat import CouncilResponse

        resp = CouncilResponse(ok=True, provider="council", reply="hi")
        self.assertIsNone(resp.council_health)


if __name__ == "__main__":
    unittest.main()
