#!/usr/bin/env python3
"""Structural checks for Tony capability truth registry v1."""

import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core import tony_capability_registry as registry  # noqa: E402


REQUIRED_KEYS = {
    "chat.answer",
    "memory.recall",
    "memory.save_low_risk",
    "briefing.today",
    "review.daily",
    "gmail.review_and_draft",
    "calendar.plan",
    "selling.draft_listing",
    "notifications.urgent",
    "code.review_local",
    "external_actions.approval_lock",
    "marketplace.live_account_actions",
    "banking.money_movement",
    "test.noop_approval",
}


class TonyCapabilityRegistryTests(unittest.TestCase):
    def test_registry_lists_required_cards_and_is_immutable(self):
        cards = registry.list_tony_capability_cards()
        keys = {card.key for card in cards}

        self.assertEqual(keys, REQUIRED_KEYS)
        self.assertEqual([card.key for card in cards], sorted(keys))
        self.assertEqual(len(keys), len(cards))
        with self.assertRaises(TypeError):
            registry.TONY_CAPABILITY_CARDS["new.card"] = cards[0]

    def test_helpers_are_safe_for_unknown_keys_and_states(self):
        self.assertIsNone(registry.get_tony_capability_card("missing.card"))
        with self.assertRaisesRegex(ValueError, "unknown_capability_state"):
            registry.list_tony_capability_cards_by_state("unknown")

    def test_every_card_has_stable_state_safe_words_and_limits(self):
        for card in registry.list_tony_capability_cards():
            self.assertIn(card.state, registry.CAPABILITY_STATES, card.key)
            self.assertTrue(card.title, card.key)
            self.assertTrue(card.user_facing_summary, card.key)
            self.assertTrue(card.safe_to_say, card.key)
            self.assertTrue(card.limits, card.key)
            self.assertIsInstance(card.limits, tuple, card.key)

    def test_available_cards_do_not_claim_external_action(self):
        for card in registry.list_tony_capability_cards_by_state(registry.AVAILABLE):
            text = " ".join(
                (card.user_facing_summary, card.safe_to_say, " ".join(card.limits))
            ).lower()
            self.assertNotIn("send email", text, card.key)
            self.assertNotIn("post marketplace", text, card.key)
            self.assertNotIn("move money", text, card.key)
            self.assertIn("no external", text, card.key)

    def test_email_calendar_and_external_actions_are_approval_required(self):
        for key in (
            "gmail.review_and_draft",
            "calendar.plan",
            "external_actions.approval_lock",
        ):
            card = registry.get_tony_capability_card(key)
            self.assertEqual(card.state, registry.APPROVAL_REQUIRED)
            text = " ".join((card.safe_to_say, " ".join(card.limits))).lower()
            self.assertIn("approval", text)

    def test_marketplace_and_banking_actions_are_blocked(self):
        for key in ("marketplace.live_account_actions", "banking.money_movement"):
            card = registry.get_tony_capability_card(key)
            self.assertEqual(card.state, registry.BLOCKED, key)
            text = " ".join((card.user_facing_summary, card.safe_to_say)).lower()
            self.assertIn("cannot", text, key)

        marketplace = registry.get_tony_capability_card(
            "marketplace.live_account_actions"
        )
        limits = " ".join(marketplace.limits).lower()
        for phrase in (
            "no autonomous posting",
            "buyer messaging",
            "offer acceptance",
            "postage purchase",
            "order handling",
            "no browser automation",
        ):
            self.assertIn(phrase, limits)

        banking = registry.get_tony_capability_card("banking.money_movement")
        self.assertIn("No bank transfer", banking.limits[0])
        self.assertIn("card payment", banking.limits[0])

    def test_test_only_card_cannot_be_generalized(self):
        card = registry.get_tony_capability_card("test.noop_approval")
        self.assertEqual(card.state, registry.TEST_ONLY)
        text = " ".join((card.user_facing_summary, card.safe_to_say, " ".join(card.limits)))
        self.assertIn("harmless no-op", text)
        self.assertIn("Must never become a generic action dispatcher.", card.limits)

    def test_low_risk_memory_card_mentions_guarded_capture_path(self):
        card = registry.get_tony_capability_card("memory.save_low_risk")
        text = " ".join((card.user_facing_summary, card.safe_to_say, " ".join(card.limits))).lower()
        self.assertIn("capture", text)
        self.assertIn("credential-like", text)

    def test_daily_loop_cards_are_limited_read_only_surfaces(self):
        for key in ("briefing.today", "review.daily"):
            card = registry.get_tony_capability_card(key)
            self.assertEqual(card.state, registry.LIMITED)
            text = " ".join((card.user_facing_summary, card.safe_to_say, " ".join(card.limits))).lower()
            self.assertIn("read-only", text)
            self.assertIn("external", text)

    def test_registry_module_imports_no_external_integrations(self):
        with open(registry.__file__, encoding="utf-8") as source_file:
            tree = ast.parse(source_file.read())

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        self.assertEqual(sorted(imports), ["dataclasses", "types"])

    def test_cards_do_not_expose_private_identifier_terms(self):
        prohibited = (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "oauth",
            "raw gmail payload",
            "request body",
            "database_url",
            "authorization header",
            "cookie",
            "session",
        )
        for card in registry.list_tony_capability_cards():
            text = " ".join(
                (
                    card.key,
                    card.title,
                    card.user_facing_summary,
                    card.safe_to_say,
                    " ".join(card.limits),
                )
            ).lower()
            for term in prohibited:
                self.assertNotIn(term, text, card.key)


if __name__ == "__main__":
    unittest.main()
