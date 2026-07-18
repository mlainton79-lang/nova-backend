import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class GapDetectorDeterministicGuardTests(unittest.TestCase):
    """The guard must return None BEFORE any classifier call for
    recall/advice-shaped messages. We prove 'before' by making the Gemini
    client explode if touched."""

    def _detect(self, message):
        from app.core import gap_detector

        with mock.patch.object(
            gap_detector, "get_conn", side_effect=AssertionError("db touched")
        ), mock.patch.dict(
            "sys.modules",
            {"app.core.gemini_client": mock.MagicMock(
                generate_content=mock.MagicMock(side_effect=AssertionError("classifier called"))
            )},
        ):
            return _run(gap_detector.detect_capability_gap(message))

    def test_birthday_planning_question_is_not_a_gap(self):
        self.assertIsNone(self._detect("What should we do for Margot's first birthday on Monday?"))

    def test_ideas_phrasing_is_not_a_gap(self):
        self.assertIsNone(self._detect("Ideas for the day?"))

    def test_should_we_and_help_me_plan_are_not_gaps(self):
        for msg in (
            "Should we take the girls to the park?",
            "Help me plan Christmas dinner",
            "What do you think about the new rota?",
            "Recommend a film for tonight",
            "Suggest something for tea",
        ):
            self.assertIsNone(self._detect(msg), msg)

    def test_existing_recall_guard_still_holds(self):
        for msg in (
            "What happened to my dad?",
            "Tell me about Nova",
            "When is Margot's birthday?",
        ):
            self.assertIsNone(self._detect(msg), msg)

    def test_guard_is_case_and_whitespace_insensitive(self):
        self.assertIsNone(self._detect("  WHAT SHOULD we do tonight?  "))

    def test_gemini_disabled_via_env_short_circuits(self):
        from app.core import gap_detector

        with mock.patch(
            "app.core.model_router_smart.is_provider_skipped", return_value=True
        ):
            result = _run(gap_detector.detect_capability_gap("Can you post to Vinted?"))
        self.assertIsNone(result)


class GapDetectorPromptContractTests(unittest.TestCase):
    def test_prompt_source_contains_advice_not_examples_and_doubt_rule(self):
        import inspect

        from app.core import gap_detector

        src = inspect.getsource(gap_detector.detect_capability_gap)
        self.assertIn("advice/planning is chat", src)
        self.assertIn("If in doubt: is_gap = false", src)
        self.assertIn("PERFORM AN ACTION", src)


class SafeModeFallThroughContractTests(unittest.TestCase):
    """The -2 (builder safe mode) branch must no longer return a refusal in
    either endpoint — safe mode degrades to answering."""

    def test_council_endpoint_has_no_safe_mode_refusal_return(self):
        src = Path("app/api/v1/endpoints/council.py").read_text()
        self.assertNotIn("Self-build is locked off for now", src)
        self.assertIn("falling through to deliberation", src)

    def test_chat_stream_endpoint_has_no_safe_mode_refusal_return(self):
        src = Path("app/api/v1/endpoints/chat_stream.py").read_text()
        self.assertNotIn("Self-build is locked off for now", src)
        self.assertIn("falling through to chat", src)


if __name__ == "__main__":
    unittest.main()
