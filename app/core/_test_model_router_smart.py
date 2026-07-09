import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ModelRouterSmartTests(unittest.TestCase):
    def test_trivial_non_greeting_routes_to_fast_provider(self):
        from app.core.model_router_smart import choose_provider

        choice = choose_provider("test")

        self.assertEqual(choice["provider"], "groq")
        self.assertIn("trivial", choice["rationale"])

    def test_short_code_request_does_not_route_as_trivial(self):
        from app.core.model_router_smart import choose_provider

        choice = choose_provider("fix bug")

        self.assertEqual(choice["provider"], "claude")

    def test_streaming_reasoning_does_not_choose_council(self):
        from app.core.model_router_smart import choose_provider

        choice = choose_provider(
            "analyse the tradeoffs and tell me what should i do next",
            is_streaming=True,
        )

        self.assertEqual(choice["provider"], "claude")


if __name__ == "__main__":
    unittest.main()
