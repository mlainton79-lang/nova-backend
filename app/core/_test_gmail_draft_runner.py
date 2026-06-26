#!/usr/bin/env python3
"""Structural checks for the disabled Gmail draft runner skeleton."""

import ast
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from app.core import approved_capability_manifest as manifest_module  # noqa: E402
from app.core import gmail_draft_runner  # noqa: E402


def _valid_snapshot():
    return {
        "to": ["matthew@example.test"],
        "cc": [],
        "bcc": [],
        "subject": "Reviewable draft subject",
        "body": "Reviewable draft body.",
        "reply_to_message_id": None,
        "user_visible_summary": "Create a Gmail draft for Matthew to review.",
        "risk_level": "low_external_write",
        "capability_key": "gmail.create_draft",
        "action_type": "gmail_create_draft",
    }


class GmailDraftRunnerTests(unittest.TestCase):
    def test_disabled_runner_module_exists_and_manifest_remains_design_only(self):
        manifest = manifest_module.get_capability_manifest("gmail.create_draft")

        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.implementation_status, "design_only")
        self.assertFalse(manifest.enabled)
        self.assertFalse(manifest.external_action_allowed)
        self.assertFalse(manifest.current_runner_connected)

    def test_disabled_runner_returns_not_connected_without_side_effect_flags(self):
        result = gmail_draft_runner.run_disabled_gmail_create_draft(_valid_snapshot())

        self.assertEqual(result.capability_key, "gmail.create_draft")
        self.assertEqual(result.action_type, "gmail_create_draft")
        self.assertEqual(result.task_type, "approved_gmail_draft_creation")
        self.assertEqual(result.status, "not_connected")
        self.assertEqual(result.verification_status, "not_run")
        self.assertFalse(result.manifest_connected)
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)
        self.assertFalse(result.draft_created)
        self.assertFalse(result.approval_grant_consumed)

    def test_disabled_runner_does_not_consume_grant_or_send_notifications(self):
        with (
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
        ):
            result = gmail_draft_runner.run_disabled_gmail_create_draft(
                _valid_snapshot()
            )

        self.assertEqual(result.status, "not_connected")
        self.assertFalse(result.draft_created)
        self.assertFalse(result.notification_sent)
        self.assertFalse(result.approval_grant_consumed)
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()

    def test_snapshot_validator_accepts_only_documented_fields(self):
        snapshot = _valid_snapshot()
        validated = gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

        self.assertEqual(validated.to, ("matthew@example.test",))
        self.assertEqual(validated.cc, ())
        self.assertEqual(validated.bcc, ())
        self.assertEqual(validated.capability_key, "gmail.create_draft")
        self.assertEqual(validated.action_type, "gmail_create_draft")

        snapshot["unexpected"] = "not allowed"
        with self.assertRaisesRegex(ValueError, "snapshot_contains_unsupported_fields"):
            gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

    def test_snapshot_validator_requires_required_fields(self):
        for field_name in (
            "to",
            "subject",
            "body",
            "user_visible_summary",
            "risk_level",
            "capability_key",
            "action_type",
        ):
            snapshot = _valid_snapshot()
            snapshot.pop(field_name)
            with self.assertRaises(ValueError):
                gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

    def test_snapshot_validator_rejects_mismatched_capability_and_action(self):
        snapshot = _valid_snapshot()
        snapshot["capability_key"] = "gmail.send_message"
        with self.assertRaisesRegex(ValueError, "snapshot_capability_mismatch"):
            gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

        snapshot = _valid_snapshot()
        snapshot["action_type"] = "gmail_send_message"
        with self.assertRaisesRegex(ValueError, "snapshot_action_type_mismatch"):
            gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

    def test_snapshot_validator_rejects_missing_content(self):
        for field_name in ("to", "subject", "body"):
            snapshot = _valid_snapshot()
            snapshot[field_name] = [] if field_name == "to" else ""
            with self.assertRaises(ValueError):
                gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

    def test_snapshot_validator_rejects_unsafe_future_operations(self):
        unsafe_terms = (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
        )
        for term in unsafe_terms:
            snapshot = _valid_snapshot()
            snapshot["body"] = term
            with self.assertRaisesRegex(
                ValueError,
                "snapshot_contains_prohibited_behavior_or_private_data",
            ):
                gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

    def test_snapshot_validator_rejects_secret_or_raw_payload_fields(self):
        for field_name in ("token", "secret", "authorization", "gmail_payload"):
            snapshot = _valid_snapshot()
            snapshot[field_name] = "redacted"
            with self.assertRaisesRegex(ValueError, "snapshot_contains_unsupported_fields"):
                gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

        snapshot = _valid_snapshot()
        snapshot["body"] = "contains access_token material"
        with self.assertRaisesRegex(
            ValueError,
            "snapshot_contains_prohibited_behavior_or_private_data",
        ):
            gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)

    def test_invalid_snapshot_returns_refused_without_draft_creation(self):
        snapshot = _valid_snapshot()
        snapshot["action_type"] = "gmail_send_message"

        result = gmail_draft_runner.run_disabled_gmail_create_draft(snapshot)

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.verification_status, "snapshot_validation_failed")
        self.assertFalse(result.external_action_performed)
        self.assertFalse(result.notification_sent)
        self.assertFalse(result.draft_created)
        self.assertFalse(result.approval_grant_consumed)

    def test_runner_module_has_no_external_or_execution_imports(self):
        with open(gmail_draft_runner.__file__, encoding="utf-8") as source_file:
            source = source_file.read()

        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        prohibited = {
            "google",
            "googleapiclient",
            "google.auth",
            "oauthlib",
            "requests_oauthlib",
            "httpx",
            "requests",
            "selenium",
            "playwright",
            "app.core.gmail_service",
            "app.core.user_notifications",
            "app.core.push_notifications",
            "app.core.approval_lock",
        }
        self.assertTrue(prohibited.isdisjoint(imports))


if __name__ == "__main__":
    unittest.main()
