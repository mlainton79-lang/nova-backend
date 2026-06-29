#!/usr/bin/env python3
"""Tests for read-only Tony capability card metadata endpoints."""

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from app.api.v1.endpoints import tony_capabilities  # noqa: E402
from app.core import tony_capability_registry as registry  # noqa: E402


class TonyCapabilityEndpointTests(unittest.TestCase):
    def test_endpoint_returns_sorted_registry_metadata_only(self):
        response = asyncio.run(
            tony_capabilities.list_tony_capability_card_metadata()
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["count"], len(registry.TONY_CAPABILITY_CARDS))
        self.assertEqual(
            [card["key"] for card in response["cards"]],
            [card.key for card in registry.list_tony_capability_cards()],
        )

        expected_fields = {
            "key",
            "state",
            "title",
            "user_facing_summary",
            "safe_to_say",
            "limits",
        }
        for card in response["cards"]:
            self.assertEqual(set(card), expected_fields)
            self.assertIsInstance(card["limits"], list)
            self.assertIn(card["state"], registry.CAPABILITY_STATES)

    def test_endpoint_does_not_expose_execution_or_approval_fields(self):
        response = asyncio.run(
            tony_capabilities.list_tony_capability_card_metadata()
        )

        blocked_fields = {
            "action",
            "action_hash",
            "approval_challenge",
            "approval_id",
            "credentials",
            "database_url",
            "grant_id",
            "oauth",
            "pending_id",
            "payload",
            "raw_payload",
            "refresh_token",
            "runner",
            "secret",
            "session",
            "token",
            "user_id",
        }
        for card in response["cards"]:
            lowered_keys = {key.lower() for key in card}
            self.assertTrue(blocked_fields.isdisjoint(lowered_keys), card["key"])

    def test_endpoint_uses_existing_auth_dependency(self):
        source = Path(tony_capabilities.__file__).read_text(encoding="utf-8")

        self.assertIn("verify_token", source)
        self.assertIn("Depends(verify_token)", source)


if __name__ == "__main__":
    unittest.main()
