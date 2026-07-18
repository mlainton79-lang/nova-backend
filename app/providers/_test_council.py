import os
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class CouncilProviderTests(unittest.TestCase):
    def test_provider_failure_keeps_class_for_empty_message_exceptions(self):
        from app.providers.council import _provider_failure

        failure = _provider_failure(TimeoutError(), "chat")

        self.assertEqual(failure["stage"], "chat")
        self.assertEqual(failure["error_class"], "TimeoutError")
        self.assertEqual(failure["message"], "(no message)")

    def test_provider_failure_truncates_message(self):
        from app.providers.council import _provider_failure

        failure = _provider_failure(RuntimeError("x" * 500), "init")

        self.assertEqual(failure["stage"], "init")
        self.assertEqual(failure["error_class"], "RuntimeError")
        self.assertEqual(len(failure["message"]), 300)


class CouncilMembershipTests(unittest.TestCase):
    def test_default_members_when_env_unset(self):
        from app.providers.council import _council_members

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COUNCIL_MEMBERS", None)
            self.assertEqual(_council_members(), ["claude", "openai", "gemini"])

    def test_default_members_when_env_empty_or_whitespace(self):
        from app.providers.council import _council_members

        for value in ("", "   ", ", ,  ,"):
            with mock.patch.dict(os.environ, {"COUNCIL_MEMBERS": value}):
                self.assertEqual(_council_members(), ["claude", "openai", "gemini"])

    def test_configured_members_parse_order_case_and_separators(self):
        from app.providers.council import _council_members

        with mock.patch.dict(os.environ, {"COUNCIL_MEMBERS": " Groq, MISTRAL  gemini "}):
            self.assertEqual(_council_members(), ["groq", "mistral", "gemini"])

    def test_unknown_members_ignored_and_duplicates_collapsed(self):
        from app.providers.council import _council_members

        with mock.patch.dict(os.environ, {"COUNCIL_MEMBERS": "claude,notreal,claude,openai"}):
            self.assertEqual(_council_members(), ["claude", "openai"])

    def test_all_unknown_falls_back_to_default(self):
        from app.providers.council import _council_members

        with mock.patch.dict(os.environ, {"COUNCIL_MEMBERS": "hal9000,skynet"}):
            self.assertEqual(_council_members(), ["claude", "openai", "gemini"])

    def test_registry_covers_default_members_and_chair_preference(self):
        from app.providers.council import (
            _ADAPTER_REGISTRY,
            CHAIR_PREFERENCE,
            DEFAULT_COUNCIL_MEMBERS,
        )

        for name in DEFAULT_COUNCIL_MEMBERS:
            self.assertIn(name, _ADAPTER_REGISTRY)
        for name in DEFAULT_COUNCIL_MEMBERS:
            self.assertIn(name, CHAIR_PREFERENCE)


class CouncilGroundingTests(unittest.TestCase):
    def test_challenge_prompt_carries_grounding_and_chair_flag(self):
        from app.providers.council import (
            CHAIR_GROUNDING_FLAG,
            GROUNDING_RULES,
            _build_challenge_prompt,
        )

        prompt = _build_challenge_prompt("ctx", "msg", "summary")
        self.assertIn(GROUNDING_RULES, prompt)
        self.assertIn(CHAIR_GROUNDING_FLAG, prompt)

    def test_refine_prompt_carries_grounding(self):
        from app.providers.council import GROUNDING_RULES, _build_refine_prompt

        successes = {"groq": "answer a", "mistral": "answer b"}
        prompt = _build_refine_prompt("groq", "ctx", "msg", successes, "challenge")
        self.assertIn(GROUNDING_RULES, prompt)
        self.assertIn("MISTRAL: answer b", prompt)
        self.assertNotIn("GROQ: answer a", prompt)

    def test_final_prompt_carries_grounding_and_personal_fact_drop_rule(self):
        from app.providers.council import GROUNDING_RULES, _build_final_prompt

        prompt = _build_final_prompt(3, "ctx", "msg", "evidence")
        self.assertIn(GROUNDING_RULES, prompt)
        self.assertIn("memory/facts blocks, drop it rather than repeat it", prompt)

    def test_grounding_rules_never_invent_language_present(self):
        from app.providers.council import GROUNDING_RULES

        for token in ("never infer", "never invent", "don't know"):
            self.assertIn(token, GROUNDING_RULES)


class CouncilHealthEnvelopeTests(unittest.TestCase):
    def test_all_seats_responding(self):
        from app.providers.council import _build_council_health

        health = _build_council_health(
            ["claude", "openai", "gemini"],
            {"claude": "a", "openai": "b", "gemini": "c"},
            {},
            [],
            chair="claude",
        )
        self.assertEqual(health["seats"], 3)
        self.assertEqual(health["responded"], 3)
        self.assertEqual(health["chair"], "claude")
        self.assertEqual(health["dark"], [])

    def test_dark_seats_carry_error_class_and_disabled_marker(self):
        from app.providers.council import _build_council_health

        failures = {"claude": {"stage": "chat", "error_class": "HTTPStatusError", "message": "400"}}
        health = _build_council_health(
            ["claude", "openai", "gemini"],
            {"openai": "b"},
            failures,
            ["gemini"],
            chair="openai",
        )
        self.assertEqual(health["seats"], 3)
        self.assertEqual(health["responded"], 1)
        self.assertEqual(health["chair"], "openai")
        dark_by_name = {d["name"]: d["error_class"] for d in health["dark"]}
        self.assertEqual(dark_by_name["claude"], "HTTPStatusError")
        self.assertEqual(dark_by_name["gemini"], "DisabledViaEnv")

    def test_unknown_dark_reason_defaults_safely(self):
        from app.providers.council import _build_council_health

        health = _build_council_health(["claude", "openai"], {"openai": "b"}, {}, [], chair="openai")
        self.assertEqual(health["dark"], [{"name": "claude", "error_class": "Unknown"}])

    def test_health_counts_only_member_successes(self):
        from app.providers.council import _build_council_health

        # A success from a non-member (should not happen, but fail safe): not counted.
        health = _build_council_health(["claude"], {"groq": "x"}, {}, [], chair=None)
        self.assertEqual(health["responded"], 0)
        self.assertEqual(health["dark"], [{"name": "claude", "error_class": "Unknown"}])


if __name__ == "__main__":
    unittest.main()
