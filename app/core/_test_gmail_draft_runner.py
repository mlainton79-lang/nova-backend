#!/usr/bin/env python3
"""Structural checks for the disabled Gmail draft runner skeleton."""

import ast
import os
import sys
import unittest
from dataclasses import replace
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

    def test_snapshot_builder_returns_exact_approved_snapshot_fields(self):
        snapshot = gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )

        self.assertEqual(
            set(snapshot),
            {
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
            },
        )
        self.assertEqual(snapshot["to"], ("matthew@example.test",))
        self.assertEqual(snapshot["cc"], ())
        self.assertEqual(snapshot["bcc"], ())
        self.assertIsNone(snapshot["reply_to_message_id"])
        self.assertEqual(snapshot["capability_key"], "gmail.create_draft")
        self.assertEqual(snapshot["action_type"], "gmail_create_draft")
        self.assertEqual(snapshot["risk_level"], "low_external_write")
        self.assertIn("Matthew to review", snapshot["user_visible_summary"])
        self.assertNotIn("send", snapshot["user_visible_summary"].lower())

    def test_snapshot_builder_accepts_typed_input_and_optional_fields(self):
        proposal = gmail_draft_runner.GmailDraftProposalInput(
            to=("matthew@example.test", "second@example.test"),
            cc="cc@example.test",
            bcc=["bcc@example.test"],
            subject="Reviewable draft subject",
            body="Reviewable draft body.",
            reply_to_message_id="message-id-from-safe-prior-flow",
        )

        snapshot = gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
            proposal
        )

        self.assertEqual(
            snapshot["to"],
            ("matthew@example.test", "second@example.test"),
        )
        self.assertEqual(snapshot["cc"], ("cc@example.test",))
        self.assertEqual(snapshot["bcc"], ("bcc@example.test",))
        self.assertEqual(
            snapshot["reply_to_message_id"],
            "message-id-from-safe-prior-flow",
        )
        validated = gmail_draft_runner.validate_gmail_draft_snapshot(snapshot)
        self.assertEqual(validated.capability_key, "gmail.create_draft")

    def test_snapshot_builder_requires_recipient_subject_and_body(self):
        for field_name in ("to", "subject", "body"):
            proposal = {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
            proposal[field_name] = "" if field_name != "to" else []
            with self.assertRaises(ValueError):
                gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
                    proposal
                )

    def test_snapshot_builder_rejects_unsafe_operations_and_bypass_approval(self):
        unsafe_terms = (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
            "bypass approval",
        )
        for term in unsafe_terms:
            with self.assertRaisesRegex(
                ValueError,
                "snapshot_contains_prohibited_behavior_or_private_data",
            ):
                gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": term,
                    }
                )

    def test_snapshot_builder_rejects_private_or_raw_payload_fields(self):
        for field_name in ("token", "secret", "authorization", "gmail_payload"):
            proposal = {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
                field_name: "redacted",
            }
            with self.assertRaisesRegex(ValueError, "proposal_contains_unsupported_fields"):
                gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
                    proposal
                )

        with self.assertRaisesRegex(
            ValueError,
            "snapshot_contains_prohibited_behavior_or_private_data",
        ):
            gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "contains refresh_token material",
                }
            )

    def test_snapshot_builder_does_not_create_approval_or_call_runner(self):
        with (
            patch(
                "app.core.gmail_draft_runner.run_disabled_gmail_create_draft",
                MagicMock(),
            ) as runner,
            patch(
                "app.core.approval_lock.create_pending_approval_once",
                MagicMock(return_value=True),
            ) as create_approval,
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
            patch(
                "app.core.user_notifications.send_user_notification",
                MagicMock(return_value=False),
            ) as notify,
        ):
            snapshot = gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )

        self.assertEqual(snapshot["capability_key"], "gmail.create_draft")
        runner.assert_not_called()
        create_approval.assert_not_called()
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()
        notify.assert_not_called()

    def test_approval_preview_adapter_returns_sanitized_review_fields(self):
        preview = gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )

        self.assertEqual(preview.capability_key, "gmail.create_draft")
        self.assertEqual(preview.action_type, "gmail_create_draft")
        self.assertEqual(preview.task_type, "approved_gmail_draft_creation")
        self.assertEqual(preview.risk_level, "low_external_write")
        self.assertEqual(preview.human_name, "Create Gmail draft")
        self.assertEqual(preview.status, "preview_only")
        self.assertIn("Matthew to review", preview.user_visible_summary)
        self.assertEqual(
            set(preview.preview_fields),
            {"to", "cc", "bcc", "subject", "body", "reply_to_message_id"},
        )
        self.assertEqual(preview.preview_fields["to"], ("matthew@example.test",))
        self.assertEqual(preview.preview_fields["subject"], "Reviewable draft subject")
        self.assertEqual(preview.preview_fields["body"], "Reviewable draft body.")
        self.assertIsNone(preview.preview_fields["reply_to_message_id"])
        self.assertFalse(preview.approval_created)
        self.assertFalse(preview.notification_sent)
        self.assertFalse(preview.external_action_performed)
        self.assertFalse(preview.draft_created)
        self.assertFalse(preview.approval_grant_consumed)

    def test_approval_preview_adapter_includes_required_warnings(self):
        preview = gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )

        for warning in (
            "draft_only",
            "not_sent",
            "no_attachments",
            "no_delete_archive_forward",
            "gmail_not_connected_yet",
            "approval_not_created_yet",
        ):
            self.assertIn(warning, preview.warnings)

    def test_approval_preview_adapter_accepts_validated_snapshot(self):
        snapshot = gmail_draft_runner.build_gmail_create_draft_approval_snapshot(
            gmail_draft_runner.GmailDraftProposalInput(
                to="matthew@example.test",
                cc="cc@example.test",
                bcc="bcc@example.test",
                subject="Reviewable draft subject",
                body="Reviewable draft body.",
                reply_to_message_id="message-id-from-safe-prior-flow",
            )
        )

        preview = gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
            snapshot
        )

        self.assertEqual(preview.preview_fields["cc"], ("cc@example.test",))
        self.assertEqual(preview.preview_fields["bcc"], ("bcc@example.test",))
        self.assertEqual(
            preview.preview_fields["reply_to_message_id"],
            "message-id-from-safe-prior-flow",
        )

    def test_approval_preview_adapter_rejects_unsafe_or_private_inputs(self):
        for body in (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
            "bypass approval",
            "contains access_token material",
        ):
            with self.assertRaises(ValueError):
                gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": body,
                    }
                )

        with self.assertRaisesRegex(ValueError, "proposal_contains_unsupported_fields"):
            gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                    "gmail_payload": "redacted",
                }
            )

    def test_approval_preview_adapter_does_not_create_or_execute_anything(self):
        with (
            patch(
                "app.core.gmail_draft_runner.run_disabled_gmail_create_draft",
                MagicMock(),
            ) as runner,
            patch(
                "app.core.approval_lock.create_pending_approval_once",
                MagicMock(return_value=True),
            ) as create_approval,
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
            patch(
                "app.core.user_notifications.send_user_notification",
                MagicMock(return_value=False),
            ) as notify,
        ):
            preview = gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )

        self.assertEqual(preview.status, "preview_only")
        runner.assert_not_called()
        create_approval.assert_not_called()
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()
        notify.assert_not_called()

    def test_approval_preview_adapter_exposes_no_private_identifier_fields(self):
        preview = gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )
        combined_keys = set(preview.preview_fields) | set(preview.__dict__)

        for forbidden in (
            "token",
            "secret",
            "gmail_payload",
            "oauth",
            "pending_id",
            "grant_id",
            "action_hash",
            "approval_challenge",
            "request_body",
        ):
            self.assertNotIn(forbidden, combined_keys)

    def test_approval_request_preview_adapter_returns_sanitized_payload(self):
        request_preview = (
            gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )

        self.assertEqual(request_preview.capability_key, "gmail.create_draft")
        self.assertEqual(request_preview.action_type, "gmail_create_draft")
        self.assertEqual(
            request_preview.task_type,
            "approved_gmail_draft_creation",
        )
        self.assertEqual(request_preview.risk_level, "low_external_write")
        self.assertEqual(request_preview.human_name, "Create Gmail draft")
        self.assertIn("Review Gmail draft", request_preview.step_summary)
        self.assertIn("Reviewable draft subject", request_preview.step_summary)
        self.assertEqual(request_preview.ttl_minutes, 10)
        self.assertTrue(request_preview.approval_required)
        self.assertEqual(request_preview.status, "request_preview_only")
        self.assertEqual(request_preview.preview.capability_key, "gmail.create_draft")
        self.assertFalse(request_preview.approval_created)
        self.assertFalse(request_preview.notification_sent)
        self.assertFalse(request_preview.external_action_performed)
        self.assertFalse(request_preview.draft_created)
        self.assertFalse(request_preview.approval_grant_consumed)

    def test_approval_request_preview_adapter_accepts_preview_and_ttl(self):
        preview = gmail_draft_runner.prepare_gmail_create_draft_approval_preview(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )

        request_preview = (
            gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                preview,
                ttl_minutes=15,
            )
        )

        self.assertEqual(request_preview.preview, preview)
        self.assertEqual(request_preview.ttl_minutes, 15)
        self.assertIn("request_preview_only", request_preview.warnings)
        self.assertIn("draft_only", request_preview.warnings)
        self.assertIn("not_sent", request_preview.warnings)
        self.assertIn("gmail_not_connected_yet", request_preview.warnings)
        self.assertIn("approval_not_created_yet", request_preview.warnings)

    def test_approval_request_preview_adapter_rejects_unsafe_or_private_inputs(self):
        for body in (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
            "bypass approval",
            "contains access_token material",
        ):
            with self.assertRaises(ValueError):
                gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": body,
                    }
                )

        with self.assertRaisesRegex(ValueError, "proposal_contains_unsupported_fields"):
            gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                    "gmail_payload": "redacted",
                }
            )

    def test_approval_request_preview_adapter_does_not_create_or_execute_anything(self):
        with (
            patch(
                "app.core.gmail_draft_runner.run_disabled_gmail_create_draft",
                MagicMock(),
            ) as runner,
            patch(
                "app.core.approval_lock.create_pending_approval_once",
                MagicMock(return_value=True),
            ) as create_approval,
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
            patch(
                "app.core.user_notifications.send_user_notification",
                MagicMock(return_value=False),
            ) as notify,
        ):
            request_preview = (
                gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": "Reviewable draft body.",
                    }
                )
            )

        self.assertEqual(request_preview.status, "request_preview_only")
        runner.assert_not_called()
        create_approval.assert_not_called()
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()
        notify.assert_not_called()

    def test_approval_request_preview_adapter_exposes_no_private_fields(self):
        request_preview = (
            gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )
        combined_keys = (
            set(request_preview.__dict__)
            | set(request_preview.preview.__dict__)
            | set(request_preview.preview.preview_fields)
        )

        self.assertEqual(
            combined_keys,
            {
                "capability_key",
                "action_type",
                "task_type",
                "risk_level",
                "human_name",
                "step_summary",
                "ttl_minutes",
                "preview",
                "approval_required",
                "status",
                "warnings",
                "approval_created",
                "notification_sent",
                "external_action_performed",
                "draft_created",
                "approval_grant_consumed",
                "user_visible_summary",
                "preview_fields",
                "to",
                "cc",
                "bcc",
                "subject",
                "body",
                "reply_to_message_id",
            },
        )
        for forbidden in (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "oauth",
            "gmail_payload",
            "request_body",
            "raw_db_rows",
        ):
            self.assertNotIn(forbidden, combined_keys)

    def test_disabled_persistence_adapter_returns_safe_insert_parameters(self):
        persistence = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )

        self.assertEqual(persistence.capability_key, "gmail.create_draft")
        self.assertEqual(persistence.action_type, "gmail_create_draft")
        self.assertEqual(persistence.task_type, "approved_gmail_draft_creation")
        self.assertIn("Review Gmail draft", persistence.step_summary)
        self.assertIn("Reviewable draft subject", persistence.step_summary)
        self.assertEqual(persistence.ttl_minutes, 10)
        self.assertEqual(persistence.request_preview_status, "request_preview_only")
        self.assertEqual(persistence.persistence_status, "disabled_preview_only")
        self.assertEqual(
            set(persistence.insert_parameters),
            {"capability_key", "action_type", "step_summary", "ttl_minutes"},
        )
        self.assertEqual(
            persistence.insert_parameters["capability_key"],
            "gmail.create_draft",
        )
        self.assertEqual(
            persistence.insert_parameters["action_type"],
            "gmail_create_draft",
        )
        self.assertEqual(persistence.insert_parameters["ttl_minutes"], 10)
        self.assertFalse(persistence.would_insert)
        self.assertFalse(persistence.approval_created)
        self.assertFalse(persistence.approval_inserted_into_database)
        self.assertFalse(persistence.notification_sent)
        self.assertFalse(persistence.external_action_performed)
        self.assertFalse(persistence.draft_created)
        self.assertFalse(persistence.approval_grant_consumed)

    def test_disabled_persistence_adapter_accepts_request_preview_and_ttl(self):
        request_preview = (
            gmail_draft_runner.prepare_gmail_create_draft_approval_request_preview(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                },
                ttl_minutes=15,
            )
        )

        persistence = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                request_preview,
                ttl_minutes=30,
            )
        )

        self.assertEqual(persistence.ttl_minutes, 15)
        self.assertEqual(persistence.insert_parameters["ttl_minutes"], 15)
        self.assertIn("request_preview_only", persistence.warnings)
        self.assertIn("persistence_disabled_preview_only", persistence.warnings)

    def test_disabled_persistence_adapter_rejects_unsafe_or_private_inputs(self):
        for body in (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
            "bypass approval",
            "contains access_token material",
        ):
            with self.assertRaises(ValueError):
                gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": body,
                    }
                )

        with self.assertRaisesRegex(ValueError, "proposal_contains_unsupported_fields"):
            gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                    "gmail_payload": "redacted",
                }
            )

    def test_disabled_persistence_adapter_does_not_create_or_execute_anything(self):
        with (
            patch(
                "app.core.gmail_draft_runner.run_disabled_gmail_create_draft",
                MagicMock(),
            ) as runner,
            patch(
                "app.core.approval_lock.create_pending_approval_once",
                MagicMock(return_value=True),
            ) as create_approval,
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
            patch(
                "app.core.user_notifications.send_user_notification",
                MagicMock(return_value=False),
            ) as notify,
        ):
            persistence = (
                gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": "Reviewable draft body.",
                    }
                )
            )

        self.assertEqual(persistence.persistence_status, "disabled_preview_only")
        runner.assert_not_called()
        create_approval.assert_not_called()
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()
        notify.assert_not_called()

    def test_disabled_persistence_adapter_exposes_no_private_fields(self):
        persistence = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )
        combined_keys = set(persistence.__dict__) | set(persistence.insert_parameters)

        self.assertEqual(
            combined_keys,
            {
                "capability_key",
                "action_type",
                "task_type",
                "step_summary",
                "ttl_minutes",
                "request_preview_status",
                "persistence_status",
                "insert_parameters",
                "warnings",
                "would_insert",
                "approval_created",
                "approval_inserted_into_database",
                "notification_sent",
                "external_action_performed",
                "draft_created",
                "approval_grant_consumed",
            },
        )
        for forbidden in (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "oauth",
            "gmail_payload",
            "request_body",
            "raw_db_rows",
            "DATABASE_URL",
            "railway_variables",
            "authorization",
        ):
            self.assertNotIn(forbidden, combined_keys)

    def test_disabled_approval_creation_wrapper_returns_sanitized_refusal(self):
        creation = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )

        self.assertEqual(creation.capability_key, "gmail.create_draft")
        self.assertEqual(creation.action_type, "gmail_create_draft")
        self.assertEqual(creation.task_type, "approved_gmail_draft_creation")
        self.assertIn("Review Gmail draft", creation.step_summary)
        self.assertIn("Reviewable draft subject", creation.step_summary)
        self.assertEqual(creation.ttl_minutes, 10)
        self.assertEqual(creation.creation_status, "disabled_before_insert")
        self.assertEqual(
            creation.refusal_reason,
            "gmail_create_draft_approval_creation_disabled",
        )
        self.assertEqual(
            set(creation.verified_insert_parameters),
            {"capability_key", "action_type", "step_summary", "ttl_minutes"},
        )
        self.assertEqual(
            creation.verified_insert_parameters["capability_key"],
            "gmail.create_draft",
        )
        self.assertEqual(
            creation.verified_insert_parameters["action_type"],
            "gmail_create_draft",
        )
        self.assertEqual(creation.verified_insert_parameters["ttl_minutes"], 10)
        self.assertFalse(creation.would_call_create_pending_approval_once)
        self.assertFalse(creation.would_insert)
        self.assertFalse(creation.approval_created)
        self.assertFalse(creation.approval_inserted_into_database)
        self.assertFalse(creation.notification_sent)
        self.assertFalse(creation.external_action_performed)
        self.assertFalse(creation.draft_created)
        self.assertFalse(creation.approval_grant_consumed)

    def test_disabled_approval_creation_wrapper_validates_persistence_preview_first(self):
        persistence = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                },
                ttl_minutes=15,
            )
        )

        creation = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                persistence,
                ttl_minutes=30,
            )
        )

        self.assertEqual(creation.ttl_minutes, 15)
        self.assertEqual(creation.verified_insert_parameters["ttl_minutes"], 15)
        self.assertIn("persistence_disabled_preview_only", creation.warnings)
        self.assertIn("creation_disabled_before_insert", creation.warnings)

        with self.assertRaisesRegex(ValueError, "persistence_preview_status_not_disabled"):
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                replace(persistence, persistence_status="enabled")
            )

    def test_disabled_approval_creation_wrapper_rejects_mutated_insert_parameters(self):
        persistence = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_pending_approval_insert(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )

        invalid_insert_parameters = (
            {},
            {
                "capability_key": "gmail.create_draft",
                "action_type": "gmail_create_draft",
                "step_summary": "Review Gmail draft",
                "ttl_minutes": 10,
                "pending_id": "not allowed",
            },
            {
                "capability_key": "gmail.send_message",
                "action_type": "gmail_create_draft",
                "step_summary": "Review Gmail draft",
                "ttl_minutes": 10,
            },
            {
                "capability_key": "gmail.create_draft",
                "action_type": "gmail_send_message",
                "step_summary": "Review Gmail draft",
                "ttl_minutes": 10,
            },
            {
                "capability_key": "gmail.create_draft",
                "action_type": "gmail_create_draft",
                "step_summary": "send this message",
                "ttl_minutes": 10,
            },
            {
                "capability_key": "gmail.create_draft",
                "action_type": "gmail_create_draft",
                "step_summary": "Review Gmail draft",
                "ttl_minutes": 0,
            },
        )
        for insert_parameters in invalid_insert_parameters:
            with self.assertRaises(ValueError):
                gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                    replace(persistence, insert_parameters=insert_parameters)
                )

    def test_disabled_approval_creation_wrapper_rejects_unsafe_or_private_inputs(self):
        for body in (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
            "bypass approval",
            "contains access_token material",
        ):
            with self.assertRaises(ValueError):
                gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": body,
                    }
                )

        with self.assertRaisesRegex(ValueError, "proposal_contains_unsupported_fields"):
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                    "gmail_payload": "redacted",
                }
            )

    def test_disabled_approval_creation_wrapper_does_not_create_or_execute_anything(self):
        with (
            patch(
                "app.core.gmail_draft_runner.run_disabled_gmail_create_draft",
                MagicMock(),
            ) as runner,
            patch(
                "app.core.approval_lock.create_pending_approval_once",
                MagicMock(return_value=True),
            ) as create_approval,
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
            patch(
                "app.core.user_notifications.send_user_notification",
                MagicMock(return_value=False),
            ) as notify,
        ):
            creation = (
                gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": "Reviewable draft body.",
                    }
                )
            )

        self.assertEqual(creation.creation_status, "disabled_before_insert")
        runner.assert_not_called()
        create_approval.assert_not_called()
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()
        notify.assert_not_called()

    def test_disabled_approval_creation_wrapper_exposes_no_private_fields(self):
        creation = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )
        combined_keys = set(creation.__dict__) | set(creation.verified_insert_parameters)

        self.assertEqual(
            combined_keys,
            {
                "capability_key",
                "action_type",
                "task_type",
                "step_summary",
                "ttl_minutes",
                "creation_status",
                "refusal_reason",
                "verified_insert_parameters",
                "warnings",
                "would_call_create_pending_approval_once",
                "would_insert",
                "approval_created",
                "approval_inserted_into_database",
                "notification_sent",
                "external_action_performed",
                "draft_created",
                "approval_grant_consumed",
            },
        )
        for forbidden in (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "oauth",
            "gmail_payload",
            "request_body",
            "raw_db_rows",
            "DATABASE_URL",
            "railway_variables",
            "authorization",
            "generated_challenge_material",
            "generated_hash_material",
        ):
            self.assertNotIn(forbidden, combined_keys)

    def test_disabled_live_approval_gate_review_returns_disabled_refusal(self):
        gate = gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )

        self.assertEqual(gate.capability_key, "gmail.create_draft")
        self.assertEqual(gate.action_type, "gmail_create_draft")
        self.assertEqual(gate.task_type, "approved_gmail_draft_creation")
        self.assertEqual(gate.gate_status, "disabled_refused")
        self.assertEqual(gate.refusal_reason, "gmail_live_approval_creation_disabled")
        self.assertFalse(gate.live_creation_enabled)
        self.assertTrue(gate.manifest_safe)
        self.assertTrue(gate.preparation_chain_valid)
        self.assertEqual(
            set(gate.verified_insert_parameters),
            {"capability_key", "action_type", "step_summary", "ttl_minutes"},
        )
        self.assertEqual(
            gate.verified_insert_parameters["capability_key"],
            "gmail.create_draft",
        )
        self.assertEqual(
            gate.verified_insert_parameters["action_type"],
            "gmail_create_draft",
        )
        self.assertEqual(gate.verified_insert_parameters["ttl_minutes"], 10)
        self.assertIn("Review Gmail draft", gate.verified_insert_parameters["step_summary"])
        self.assertIn("live_approval_gate_disabled", gate.warnings)
        self.assertFalse(gate.would_call_create_pending_approval_once)
        self.assertFalse(gate.would_insert)
        self.assertFalse(gate.approval_created)
        self.assertFalse(gate.approval_inserted_into_database)
        self.assertFalse(gate.notification_sent)
        self.assertFalse(gate.external_action_performed)
        self.assertFalse(gate.draft_created)
        self.assertFalse(gate.approval_grant_consumed)

    def test_disabled_live_approval_gate_confirms_manifest_is_not_connected(self):
        manifest = manifest_module.get_capability_manifest("gmail.create_draft")
        gate = gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            },
            ttl_minutes=15,
        )

        self.assertEqual(manifest.implementation_status, "design_only")
        self.assertFalse(manifest.enabled)
        self.assertFalse(manifest.external_action_allowed)
        self.assertFalse(manifest.current_runner_connected)
        self.assertTrue(gate.manifest_safe)
        self.assertEqual(gate.verified_insert_parameters["ttl_minutes"], 15)
        self.assertFalse(gmail_draft_runner.is_gmail_create_draft_live_approval_enabled())

    def test_disabled_live_approval_gate_review_accepts_creation_preview(self):
        creation = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                },
                ttl_minutes=15,
            )
        )

        gate = gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
            creation,
            ttl_minutes=30,
        )

        self.assertEqual(gate.verified_insert_parameters["ttl_minutes"], 15)
        self.assertIn("creation_disabled_before_insert", gate.warnings)
        self.assertIn("live_approval_gate_disabled", gate.warnings)

    def test_disabled_live_approval_gate_review_rejects_mutated_creation_preview(self):
        creation = (
            gmail_draft_runner.prepare_disabled_gmail_create_draft_approval_creation(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )
        )

        invalid_creation_previews = (
            replace(creation, creation_status="enabled"),
            replace(creation, would_call_create_pending_approval_once=True),
            replace(creation, would_insert=True),
            replace(creation, approval_created=True),
            replace(creation, approval_inserted_into_database=True),
            replace(creation, notification_sent=True),
            replace(creation, external_action_performed=True),
            replace(creation, draft_created=True),
            replace(creation, approval_grant_consumed=True),
            replace(
                creation,
                verified_insert_parameters={
                    "capability_key": "gmail.create_draft",
                    "action_type": "gmail_create_draft",
                    "step_summary": "Review Gmail draft",
                    "ttl_minutes": 10,
                    "approval_challenge": "not allowed",
                },
            ),
            replace(
                creation,
                verified_insert_parameters={
                    "capability_key": "gmail.create_draft",
                    "action_type": "gmail_create_draft",
                    "step_summary": "Review Gmail draft",
                    "ttl_minutes": 0,
                },
            ),
        )
        for invalid_creation_preview in invalid_creation_previews:
            with self.assertRaises(ValueError):
                gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
                    invalid_creation_preview
                )

    def test_disabled_live_approval_gate_review_rejects_unsafe_or_private_inputs(self):
        for body in (
            "send this message",
            "delete the email",
            "archive the thread",
            "forward the message",
            "perform broad inbox read",
            "add an attachment",
            "modify existing draft",
            "bypass approval",
            "contains access_token material",
        ):
            with self.assertRaises(ValueError):
                gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
                    {
                        "to": "matthew@example.test",
                        "subject": "Reviewable draft subject",
                        "body": body,
                    }
                )

        with self.assertRaisesRegex(ValueError, "proposal_contains_unsupported_fields"):
            gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                    "gmail_payload": "redacted",
                }
            )

    def test_disabled_live_approval_gate_does_not_create_or_execute_anything(self):
        with (
            patch(
                "app.core.gmail_draft_runner.run_disabled_gmail_create_draft",
                MagicMock(),
            ) as runner,
            patch(
                "app.core.approval_lock.create_pending_approval_once",
                MagicMock(return_value=True),
            ) as create_approval,
            patch(
                "app.core.approval_lock.consume_test_approval_resume_grant",
                MagicMock(return_value=True),
            ) as resume_consume,
            patch(
                "app.core.approval_lock.consume_test_approved_noop_grant",
                MagicMock(return_value=True),
            ) as noop_consume,
            patch(
                "app.core.user_notifications.send_user_notification",
                MagicMock(return_value=False),
            ) as notify,
        ):
            gate = gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
                {
                    "to": "matthew@example.test",
                    "subject": "Reviewable draft subject",
                    "body": "Reviewable draft body.",
                }
            )

        self.assertEqual(gate.gate_status, "disabled_refused")
        runner.assert_not_called()
        create_approval.assert_not_called()
        resume_consume.assert_not_called()
        noop_consume.assert_not_called()
        notify.assert_not_called()

    def test_disabled_live_approval_gate_exposes_no_private_fields(self):
        gate = gmail_draft_runner.review_disabled_gmail_create_draft_live_approval_gate(
            {
                "to": "matthew@example.test",
                "subject": "Reviewable draft subject",
                "body": "Reviewable draft body.",
            }
        )
        combined_keys = set(gate.__dict__) | set(gate.verified_insert_parameters)

        self.assertEqual(
            combined_keys,
            {
                "capability_key",
                "action_type",
                "task_type",
                "gate_status",
                "refusal_reason",
                "live_creation_enabled",
                "manifest_safe",
                "preparation_chain_valid",
                "verified_insert_parameters",
                "warnings",
                "would_call_create_pending_approval_once",
                "would_insert",
                "approval_created",
                "approval_inserted_into_database",
                "notification_sent",
                "external_action_performed",
                "draft_created",
                "approval_grant_consumed",
                "step_summary",
                "ttl_minutes",
            },
        )
        for forbidden in (
            "pending_id",
            "approval_challenge",
            "action_hash",
            "grant_id",
            "token",
            "secret",
            "oauth",
            "gmail_payload",
            "request_body",
            "raw_db_rows",
            "DATABASE_URL",
            "railway_variables",
            "authorization",
            "generated_challenge_material",
            "generated_hash_material",
        ):
            self.assertNotIn(forbidden, combined_keys)

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
