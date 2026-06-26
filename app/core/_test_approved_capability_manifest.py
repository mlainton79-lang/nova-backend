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
        self.assertEqual(len(manifests), 3)
        self.assertEqual(
            set(manifests),
            {
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.TEST_APPROVED_NOOP_CAPABILITY_KEY,
                manifest_module.GMAIL_CREATE_DRAFT_CAPABILITY_KEY,
            },
        )
        with self.assertRaises(TypeError):
            manifests["test.extra"] = manifest_module.TEST_APPROVAL_RESUME_MANIFEST

    def test_each_manifest_declares_test_only_no_external_runner_policy(self):
        for item in (
            manifest_module.TEST_APPROVAL_RESUME_MANIFEST,
            manifest_module.TEST_APPROVED_NOOP_MANIFEST,
        ):
            self.assertEqual(item.risk_level, "test_only")
            self.assertTrue(item.approval_required)
            self.assertFalse(item.external_action_allowed)
            self.assertFalse(item.notification_allowed)
            self.assertEqual(item.runner_type, "no_op_approved_runner")
            self.assertEqual(item.implementation_status, "connected")
            self.assertTrue(item.enabled)
            self.assertTrue(item.current_runner_connected)
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

    def test_gmail_create_draft_is_registered_design_only_and_not_executable(self):
        manifest = manifest_module.get_capability_manifest("gmail.create_draft")

        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.capability_key, "gmail.create_draft")
        self.assertEqual(manifest.action_type, "gmail_create_draft")
        self.assertEqual(manifest.task_type, "approved_gmail_draft_creation")
        self.assertEqual(manifest.human_name, "Create Gmail draft")
        self.assertEqual(manifest.risk_level, "low_external_write")
        self.assertTrue(manifest.approval_required)
        self.assertFalse(manifest.external_action_allowed)
        self.assertFalse(manifest.notification_allowed)
        self.assertEqual(manifest.runner_type, "gmail_draft_runner")
        self.assertEqual(manifest.implementation_status, "design_only")
        self.assertFalse(manifest.enabled)
        self.assertFalse(manifest.current_runner_connected)
        self.assertFalse(manifest_module.is_safe_noop_runner_manifest(manifest))
        self.assertIn(
            "gmail.create_draft",
            manifest_module.list_design_only_capabilities(),
        )
        self.assertNotIn(
            "gmail.create_draft",
            manifest_module.list_safe_test_capabilities(),
        )
        with self.assertRaisesRegex(ValueError, "capability_not_connected"):
            manifest_module.assert_capability_can_use_runner(
                "gmail.create_draft",
                "gmail_draft_runner",
            )

    def test_gmail_approval_snapshot_contract_is_documented(self):
        manifest = manifest_module.GMAIL_CREATE_DRAFT_MANIFEST

        self.assertEqual(
            manifest.approval_snapshot_required_fields,
            (
                "to",
                "cc",
                "bcc",
                "subject",
                "body",
                "reply_to_message_id",
                "user_visible_summary",
                "risk_level",
                "capability_key",
                "action_type",
            ),
        )
        self.assertIn("recipient_list_explicit_and_user_visible", manifest.preconditions)
        self.assertIn(
            "subject_and_body_explicit_and_user_visible",
            manifest.preconditions,
        )
        self.assertIn("no_send_flag_present", manifest.preconditions)
        self.assertIn("no_attachment_instruction_present", manifest.preconditions)

    def test_gmail_scope_verification_and_fail_closed_contracts_are_documented(self):
        manifest = manifest_module.GMAIL_CREATE_DRAFT_MANIFEST

        for operation in (
            "send",
            "delete",
            "archive",
            "forward",
            "broad_inbox_read",
            "attachments",
            "modify_existing_draft",
        ):
            self.assertIn(operation, manifest.out_of_scope_operations)

        for requirement in (
            "gmail_api_returned_draft_created_success",
            "created_object_is_draft_not_sent_message",
            "recipient_subject_body_match_approved_snapshot",
            "safe_result_reports_only_sanitized_metadata",
            "failure_not_reported_completed_without_verified_draft_creation",
        ):
            self.assertIn(requirement, manifest.verification_requirements)

        for condition in (
            "manifest_missing",
            "manifest_design_only_or_not_connected",
            "approval_missing_expired_rejected_consumed_or_mismatched",
            "approved_snapshot_missing_required_fields",
            "snapshot_includes_send_delete_archive_forward_attachment_or_broad_read",
            "draft_creation_verification_failed",
            "secret_token_raw_gmail_payload_exposure_risk",
        ):
            self.assertIn(condition, manifest.fail_closed_if)

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
