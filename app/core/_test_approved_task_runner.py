#!/usr/bin/env python3
"""Structural checks for Approved Task Runner Adapter v1."""

import ast
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from app.core import approved_task_runner  # noqa: E402
from app.core import approval_lock  # noqa: E402
from app.core import approved_capability_manifest  # noqa: E402


class ApprovedTaskRunnerTests(unittest.TestCase):
    def test_resume_runner_is_fixed_to_harmless_test_contract(self):
        consume = MagicMock(return_value=True)
        with patch.object(
            approved_task_runner,
            "consume_test_approval_resume_grant",
            consume,
        ):
            result = approved_task_runner.run_harmless_test_approval_resume()

        consume.assert_called_once_with()
        self.assertEqual(
            approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
            "test.approval_resume",
        )
        self.assertEqual(
            result.capability_key,
            approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
        )
        self.assertEqual(
            result.task_type,
            approved_capability_manifest.TEST_APPROVAL_RESUME_MANIFEST.task_type,
        )
        self.assertTrue(result.resumed)
        self.assertEqual(result.safe_status, "completed")
        self.assertEqual(
            result.safe_message,
            approved_task_runner.HARMLESS_RESUME_COMPLETED_MESSAGE,
        )
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)
        self.assertEqual(result.verification_status, "no_op_verified")

    def test_runner_returns_not_resumed_without_eligible_grant(self):
        consume = MagicMock(return_value=False)
        with patch.object(
            approved_task_runner,
            "consume_test_approval_resume_grant",
            consume,
        ):
            result = approved_task_runner.run_harmless_test_approval_resume()

        consume.assert_called_once_with()
        self.assertFalse(result.resumed)
        self.assertEqual(result.safe_status, "not_resumed")
        self.assertEqual(
            result.safe_message,
            approved_task_runner.HARMLESS_RESUME_NOT_RESUMED_MESSAGE,
        )
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)
        self.assertEqual(result.verification_status, "not_run")

    def test_second_consume_cannot_produce_second_completed_result(self):
        consume = MagicMock(side_effect=[True, False])
        with patch.object(
            approved_task_runner,
            "consume_test_approval_resume_grant",
            consume,
        ):
            first = approved_task_runner.run_harmless_test_approval_resume()
            second = approved_task_runner.run_harmless_test_approval_resume()

        self.assertTrue(first.resumed)
        self.assertFalse(second.resumed)
        self.assertEqual(second.safe_status, "not_resumed")
        self.assertEqual(consume.call_count, 2)

    def test_noop_runner_is_fixed_to_second_test_capability(self):
        consume = MagicMock(return_value=True)
        with patch.object(
            approved_task_runner,
            "consume_test_approved_noop_grant",
            consume,
        ):
            result = approved_task_runner.run_harmless_test_approved_noop()

        consume.assert_called_once_with()
        self.assertEqual(
            result.capability_key,
            approval_lock.TEST_APPROVED_NOOP_CAPABILITY_KEY,
        )
        self.assertEqual(
            result.task_type,
            approved_capability_manifest.TEST_APPROVED_NOOP_MANIFEST.task_type,
        )
        self.assertTrue(result.resumed)
        self.assertEqual(result.safe_status, "completed")
        self.assertEqual(
            result.safe_message,
            approved_task_runner.HARMLESS_NOOP_COMPLETED_MESSAGE,
        )
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)

    def test_noop_runner_returns_not_resumed_after_consumption(self):
        consume = MagicMock(side_effect=[True, False])
        with patch.object(
            approved_task_runner,
            "consume_test_approved_noop_grant",
            consume,
        ):
            first = approved_task_runner.run_harmless_test_approved_noop()
            second = approved_task_runner.run_harmless_test_approved_noop()

        self.assertTrue(first.resumed)
        self.assertFalse(second.resumed)
        self.assertEqual(second.safe_status, "not_resumed")
        self.assertFalse(second.external_action_performed)
        self.assertFalse(second.notification_sent)

    def test_manifest_allowlists_only_the_two_harmless_capabilities(self):
        manifests = approved_capability_manifest.APPROVED_CAPABILITY_MANIFESTS
        self.assertEqual(
            set(manifests),
            {
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.TEST_APPROVED_NOOP_CAPABILITY_KEY,
            },
        )
        for manifest in manifests.values():
            self.assertEqual(manifest.risk_level, "test_only")
            self.assertTrue(manifest.approval_required)
            self.assertFalse(manifest.external_action_allowed)
            self.assertFalse(manifest.notification_allowed)
            self.assertEqual(manifest.runner_type, "no_op_approved_runner")
            self.assertIn("no_op_verified", manifest.verification_requirements)
            self.assertIn("completed", manifest.allowed_outputs)
            self.assertIn("not_resumed", manifest.allowed_outputs)

    def test_runner_fails_closed_when_manifest_is_not_safe_noop(self):
        unsafe_manifest = approved_capability_manifest.ApprovedCapabilityManifest(
            capability_key="test.unsafe",
            action_type="test_unsafe",
            task_type="unsafe_test",
            human_name="Unsafe test",
            description="Synthetic unsafe manifest.",
            risk_level="test_only",
            approval_required=True,
            external_action_allowed=True,
            notification_allowed=False,
            runner_type="no_op_approved_runner",
            preconditions=("approved_pending_approval",),
            verification_requirements=("no_op_verified",),
            allowed_outputs=("not_resumed",),
        )
        consume = MagicMock(return_value=True)
        runner = approved_task_runner._NoOpApprovedCapabilityRunner(
            manifest=unsafe_manifest,
            completed_message="must not be returned",
            not_resumed_message="blocked by manifest",
            consume_once=consume,
        )

        result = runner.run()

        consume.assert_not_called()
        self.assertFalse(result.resumed)
        self.assertEqual(result.safe_status, "not_resumed")
        self.assertEqual(result.verification_status, "manifest_not_eligible")

    def test_runner_module_has_no_external_or_notification_dependencies(self):
        with open(approved_task_runner.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        prohibited = {
            "httpx",
            "requests",
            "selenium",
            "playwright",
            "app.core.user_notifications",
            "app.core.push_notifications",
            "app.core.gmail_service",
            "app.core.ebay_oauth",
        }
        self.assertTrue(prohibited.isdisjoint(imports))


if __name__ == "__main__":
    unittest.main()
