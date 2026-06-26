#!/usr/bin/env python3
"""Structural checks for Capability Manifest v1."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from app.core import approval_lock  # noqa: E402
from app.core import approved_capability_manifest as manifest_module  # noqa: E402


class ApprovedCapabilityManifestTests(unittest.TestCase):
    def test_manifest_is_immutable_and_contains_only_safe_test_capabilities(self):
        manifests = manifest_module.APPROVED_CAPABILITY_MANIFESTS
        self.assertEqual(len(manifests), 2)
        self.assertEqual(
            set(manifests),
            {
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.TEST_APPROVED_NOOP_CAPABILITY_KEY,
            },
        )
        with self.assertRaises(TypeError):
            manifests["test.extra"] = manifest_module.TEST_APPROVAL_RESUME_MANIFEST

    def test_each_manifest_declares_test_only_no_external_runner_policy(self):
        for item in manifest_module.APPROVED_CAPABILITY_MANIFESTS.values():
            self.assertEqual(item.risk_level, "test_only")
            self.assertTrue(item.approval_required)
            self.assertFalse(item.external_action_allowed)
            self.assertFalse(item.notification_allowed)
            self.assertEqual(item.runner_type, "no_op_approved_runner")
            self.assertIn("no_op_verified", item.verification_requirements)
            self.assertTrue(manifest_module.is_safe_noop_runner_manifest(item))

    def test_unknown_capability_has_no_manifest(self):
        self.assertIsNone(
            manifest_module.get_approved_capability_manifest("test.unknown")
        )
        self.assertIsNone(manifest_module.get_capability_manifest("test.unknown"))
        self.assertFalse(manifest_module.is_capability_registered("test.unknown"))

    def test_requested_helpers_expose_only_safe_registered_test_capabilities(self):
        safe_capabilities = manifest_module.list_safe_test_capabilities()

        self.assertEqual(
            set(safe_capabilities),
            {
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.TEST_APPROVED_NOOP_CAPABILITY_KEY,
            },
        )
        for capability_key in safe_capabilities:
            self.assertTrue(manifest_module.is_capability_registered(capability_key))
            manifest = manifest_module.assert_capability_can_use_runner(
                capability_key,
                "no_op_approved_runner",
            )
            self.assertEqual(manifest.capability_key, capability_key)
            self.assertTrue(manifest.approval_required)
            self.assertFalse(manifest.external_action_allowed)
            self.assertFalse(manifest.notification_allowed)

    def test_unregistered_capability_and_runner_mismatch_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "capability_not_registered"):
            manifest_module.assert_capability_can_use_runner(
                "test.unknown",
                "no_op_approved_runner",
            )

        with self.assertRaisesRegex(ValueError, "capability_runner_mismatch"):
            manifest_module.assert_capability_can_use_runner(
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                "external_api_runner",
            )

    def test_manifest_module_imports_no_external_integrations(self):
        with open(manifest_module.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        prohibited = (
            "app.core.gmail_service",
            "app.core.calendar_service",
            "app.core.ebay_oauth",
            "app.core.vinted",
            "app.core.browser_agent",
            "requests",
            "httpx",
            "selenium",
            "playwright",
        )
        for import_name in prohibited:
            self.assertNotIn(import_name, source)


if __name__ == "__main__":
    unittest.main()
