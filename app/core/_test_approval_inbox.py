#!/usr/bin/env python3
"""Structural tests for the read-only approval inbox."""

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from fastapi import FastAPI
import httpx

from app.api.v1.endpoints.approvals import router as approvals_router  # noqa: E402
from app.core.security import verify_token  # noqa: E402
from app.core import approval_lock  # noqa: E402
from app.core.user_notifications import NotificationType  # noqa: E402


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, rows):
        self.cursor_instance = _Cursor(rows)
        self.closed = False
        self.committed = False
        self.rolled_back = False
        self.autocommit = True

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class ApprovalInboxTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(approvals_router, prefix="/api/v1")

    def _request(self, method: str, path: str):
        async def _run():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path)

        return asyncio.run(_run())

    def test_endpoint_is_protected(self):
        response = self._request("GET", "/api/v1/approvals/pending")
        self.assertEqual(response.status_code, 422)

    def test_test_pending_endpoint_is_protected(self):
        response = self._request("POST", "/api/v1/approvals/test-pending")
        self.assertEqual(response.status_code, 422)

    def test_reject_endpoint_is_protected(self):
        pending_id = str(uuid.uuid4())
        response = self._request("POST", f"/api/v1/approvals/{pending_id}/reject")
        self.assertEqual(response.status_code, 422)

    def test_approve_endpoint_is_protected(self):
        pending_id = str(uuid.uuid4())
        response = self._request("POST", f"/api/v1/approvals/{pending_id}/approve")
        self.assertEqual(response.status_code, 422)

    def test_resume_test_endpoints_are_protected(self):
        pending = self._request("POST", "/api/v1/approvals/test-resume-pending")
        run = self._request("POST", "/api/v1/approvals/test-resume-run")
        self.assertEqual(pending.status_code, 422)
        self.assertEqual(run.status_code, 422)

    def test_awaiting_approval_can_be_denied(self):
        pending_id = str(uuid.uuid4())
        connection = _Connection(rows=[(pending_id,)])

        with patch.object(approval_lock, "_connect", return_value=connection):
            rejected = approval_lock.reject_pending_approval(pending_id)

        self.assertTrue(rejected)
        self.assertTrue(connection.committed)
        statement, params = connection.cursor_instance.statements[0]
        normalized_statement = " ".join(statement.split())
        self.assertIn("SET status = 'denied'", normalized_statement)
        self.assertIn("denied_at = NOW()", normalized_statement)
        self.assertIn("denied_by_device_id = ( SELECT device_id", normalized_statement)
        self.assertIn("approval_challenge_used_at = NOW()", normalized_statement)
        self.assertIn("WHERE pending_id::text = %s", normalized_statement)
        self.assertIn("AND status = 'awaiting'", normalized_statement)
        self.assertIn("WHERE status = 'active'", normalized_statement)
        self.assertNotIn("DELETE", normalized_statement.upper())
        self.assertEqual(params, (pending_id,))

    def test_non_uuid_pending_approval_id_can_be_denied(self):
        pending_id = "test-pending-approval-id"
        connection = _Connection(rows=[(pending_id,)])

        with patch.object(approval_lock, "_connect", return_value=connection):
            rejected = approval_lock.reject_pending_approval(pending_id)

        self.assertTrue(rejected)
        statement, params = connection.cursor_instance.statements[0]
        normalized_statement = " ".join(statement.split())
        self.assertIn("SET status = 'denied'", normalized_statement)
        self.assertIn("denied_at = NOW()", normalized_statement)
        self.assertIn("denied_by_device_id = ( SELECT device_id", normalized_statement)
        self.assertIn("approval_challenge_used_at = NOW()", normalized_statement)
        self.assertIn("WHERE pending_id::text = %s", normalized_statement)
        self.assertIn("AND status = 'awaiting'", normalized_statement)
        self.assertIn("WHERE status = 'active'", normalized_statement)
        self.assertNotIn("DELETE", normalized_statement.upper())
        self.assertEqual(params, (pending_id,))

    def test_invalid_pending_approval_id_is_not_queried(self):
        connection = _Connection(rows=[("ignored",)])

        with patch.object(approval_lock, "_connect", return_value=connection):
            rejected = approval_lock.reject_pending_approval("")

        self.assertFalse(rejected)
        self.assertEqual(connection.cursor_instance.statements, [])

    def test_awaiting_approval_can_be_marked_approved(self):
        pending_id = str(uuid.uuid4())
        connection = _Connection(rows=[(pending_id,)])

        with patch.object(approval_lock, "_connect", return_value=connection):
            approved = approval_lock.approve_pending_approval(pending_id)

        self.assertTrue(approved)
        self.assertTrue(connection.committed)
        device_statement, device_params = connection.cursor_instance.statements[0]
        grant_statement, grant_params = connection.cursor_instance.statements[1]
        update_statement, update_params = connection.cursor_instance.statements[2]
        normalized_device = " ".join(device_statement.split())
        normalized_insert = " ".join(grant_statement.split())
        normalized_update = " ".join(update_statement.split())
        self.assertIn("INSERT INTO tony_approval_devices", normalized_device)
        self.assertIn("status, revoked_at", normalized_device)
        self.assertIn("SELECT %s, %s, %s, 'revoked', NOW()", normalized_device)
        self.assertIn("WHERE NOT EXISTS", normalized_device)
        self.assertEqual(device_params[1], "dev-token approval metadata")
        self.assertIn("INSERT INTO tony_action_grants", normalized_insert)
        self.assertIn("WHERE pending.pending_id::text = %s", normalized_insert)
        self.assertIn("AND pending.status = 'awaiting'", normalized_insert)
        self.assertIn("AND pending.expires_at > NOW()", normalized_insert)
        self.assertIn("ON CONFLICT (pending_action_ref) DO UPDATE", normalized_insert)
        self.assertIn("SET status = 'active'", normalized_insert)
        self.assertIn("tony_action_grants.consumed_at IS NULL", normalized_insert)
        self.assertIn("SET status = 'approved'", normalized_update)
        self.assertIn("approved_at = NOW()", normalized_update)
        self.assertIn("approved_by_device_id = (", normalized_update)
        self.assertIn("approval_challenge_used_at = NOW()", normalized_update)
        self.assertIn("grant_id = %s", normalized_update)
        self.assertIn("WHERE pending_id::text = %s", normalized_update)
        self.assertIn("AND status = 'awaiting'", normalized_update)
        self.assertIn("AND expires_at > NOW()", normalized_update)
        combined_statement = f"{normalized_insert} {normalized_update}"
        self.assertNotIn("DELETE", combined_statement.upper())
        self.assertNotIn("send_user_notification", combined_statement)
        self.assertEqual(grant_params[1], pending_id)
        self.assertEqual(update_params[1], pending_id)

    def test_test_resume_grant_can_be_consumed_once(self):
        connection = _Connection(rows=[(str(uuid.uuid4()),)])

        with patch.object(approval_lock, "_connect", return_value=connection):
            consumed = approval_lock.consume_test_approval_resume_grant()

        self.assertTrue(consumed)
        self.assertTrue(connection.committed)
        statement, params = connection.cursor_instance.statements[0]
        normalized_statement = " ".join(statement.split())
        self.assertIn("WITH selected_grant AS", normalized_statement)
        self.assertIn("FROM tony_action_grants action_grant", normalized_statement)
        self.assertIn("JOIN tony_pending_approvals pending_approval", normalized_statement)
        self.assertIn("action_grant.capability_key = %s", normalized_statement)
        self.assertIn("pending_approval.capability_key = %s", normalized_statement)
        self.assertIn("pending_approval.status = %s", normalized_statement)
        self.assertIn("action_grant.status = %s", normalized_statement)
        self.assertIn("action_grant.consumed_at IS NULL", normalized_statement)
        self.assertIn("action_grant.expires_at > NOW()", normalized_statement)
        self.assertIn("pending_approval.expires_at > NOW()", normalized_statement)
        self.assertIn("FOR UPDATE OF action_grant", normalized_statement)
        self.assertIn("SET status = %s", normalized_statement)
        self.assertIn("consumed_at = NOW()", normalized_statement)
        self.assertNotIn("DELETE", normalized_statement.upper())
        self.assertNotIn(" tony_action_grants grant ", normalized_statement)
        self.assertEqual(
            params,
            (
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.PENDING_APPROVAL_STATUS_APPROVED,
                approval_lock.ACTION_GRANT_STATUS_ACTIVE,
                approval_lock.ACTION_GRANT_STATUS_CONSUMED,
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.ACTION_GRANT_STATUS_ACTIVE,
            ),
        )

    def test_test_resume_grant_missing_or_already_consumed_returns_false(self):
        connection = _Connection(rows=[])

        with patch.object(approval_lock, "_connect", return_value=connection):
            consumed = approval_lock.consume_test_approval_resume_grant()

        self.assertFalse(consumed)
        statement, _ = connection.cursor_instance.statements[0]
        normalized_statement = " ".join(statement.split())
        self.assertIn("action_grant.status = %s", normalized_statement)
        self.assertIn("action_grant.consumed_at IS NULL", normalized_statement)

    def test_resume_contract_requires_approved_unexpired_active_grant(self):
        connection = _Connection(rows=[])

        with patch.object(approval_lock, "_connect", return_value=connection):
            consumed = approval_lock.consume_test_approval_resume_grant()

        self.assertFalse(consumed)
        statement, params = connection.cursor_instance.statements[0]
        normalized_statement = " ".join(statement.split())
        self.assertIn("pending_approval.status = %s", normalized_statement)
        self.assertIn("pending_approval.expires_at > NOW()", normalized_statement)
        self.assertIn("action_grant.status = %s", normalized_statement)
        self.assertIn("action_grant.expires_at > NOW()", normalized_statement)
        self.assertIn("action_grant.consumed_at IS NULL", normalized_statement)
        self.assertIn("SET status = %s", normalized_statement)
        self.assertEqual(
            params,
            (
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.PENDING_APPROVAL_STATUS_APPROVED,
                approval_lock.ACTION_GRANT_STATUS_ACTIVE,
                approval_lock.ACTION_GRANT_STATUS_CONSUMED,
                approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
                approval_lock.ACTION_GRANT_STATUS_ACTIVE,
            ),
        )

    def test_test_resume_wrapper_cannot_consume_non_test_capability(self):
        consume = MagicMock(return_value=True)
        with patch.object(approval_lock, "_consume_approved_grant_once", consume):
            consumed = approval_lock.consume_test_approval_resume_grant()

        self.assertTrue(consumed)
        consume.assert_called_once_with(
            capability_key=approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
        )

    def test_non_existent_approval_returns_false_when_marking_approved(self):
        pending_id = str(uuid.uuid4())
        connection = _Connection(rows=[])

        with patch.object(approval_lock, "_connect", return_value=connection):
            approved = approval_lock.approve_pending_approval(pending_id)

        self.assertFalse(approved)
        self.assertTrue(connection.rolled_back)

    def test_reject_endpoint_returns_sanitized_outcomes(self):
        self.app.dependency_overrides[verify_token] = lambda: True
        reject = MagicMock(side_effect=[True, False])
        first_id = str(uuid.uuid4())
        missing_id = str(uuid.uuid4())
        with patch(
            "app.api.v1.endpoints.approvals.reject_pending_approval",
            reject,
        ):
            rejected = self._request(
                "POST", f"/api/v1/approvals/{first_id}/reject"
            )
            missing = self._request(
                "POST", f"/api/v1/approvals/{missing_id}/reject"
            )
        self.app.dependency_overrides.clear()

        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertTrue(rejected.json()["rejected"])
        self.assertFalse(missing.json()["rejected"])
        self.assertEqual(set(rejected.json()), {"ok", "rejected", "status", "message"})
        self.assertEqual(set(missing.json()), {"ok", "rejected", "status", "message"})

    def test_approve_endpoint_returns_sanitized_outcomes(self):
        self.app.dependency_overrides[verify_token] = lambda: True
        approve = MagicMock(side_effect=[True, False])
        resume = MagicMock(return_value=True)
        first_id = str(uuid.uuid4())
        missing_id = str(uuid.uuid4())
        with (
            patch(
                "app.api.v1.endpoints.approvals.approve_pending_approval",
                approve,
            ),
            patch(
                "app.api.v1.endpoints.approvals.consume_test_approval_resume_grant",
                resume,
            ),
        ):
            approved = self._request(
                "POST", f"/api/v1/approvals/{first_id}/approve"
            )
            missing = self._request(
                "POST", f"/api/v1/approvals/{missing_id}/approve"
            )
        self.app.dependency_overrides.clear()

        self.assertEqual(approved.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertTrue(approved.json()["approved"])
        self.assertFalse(missing.json()["approved"])
        allowed_keys = {"ok", "approved", "status", "message"}
        self.assertEqual(set(approved.json()), allowed_keys)
        self.assertEqual(set(missing.json()), allowed_keys)
        for payload in (approved.json(), missing.json()):
            self.assertNotIn("approval_challenge", payload)
            self.assertNotIn("action_hash", payload)
            self.assertNotIn("pending_id", payload)
            self.assertNotIn("token", payload)
            self.assertNotIn("secret", payload)
        resume.assert_not_called()

    def test_test_pending_creates_once_and_notifies_once(self):
        self.app.dependency_overrides[verify_token] = lambda: True
        create = MagicMock(side_effect=[True, False])
        notify = AsyncMock(return_value=True)
        with (
            patch(
                "app.api.v1.endpoints.approvals.create_pending_approval_once",
                create,
            ),
            patch(
                "app.api.v1.endpoints.approvals.send_user_notification",
                notify,
            ),
        ):
            first = self._request("POST", "/api/v1/approvals/test-pending")
            duplicate = self._request("POST", "/api/v1/approvals/test-pending")
        self.app.dependency_overrides.clear()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(first.json()["created"])
        self.assertFalse(duplicate.json()["created"])
        notify.assert_awaited_once_with(NotificationType.APPROVAL_REQUIRED)
        create.assert_called_with(
            capability_key="test.approval_inbox",
            action_type="test_pending_approval",
            step_summary="Test approval for Android Approval Inbox display",
            ttl_minutes=10,
        )

        allowed_keys = {"ok", "created", "status", "message"}
        self.assertEqual(set(first.json()), allowed_keys)
        self.assertEqual(set(duplicate.json()), allowed_keys)
        for payload in (first.json(), duplicate.json()):
            self.assertNotIn("approval_challenge", payload)
            self.assertNotIn("action_hash", payload)

    def test_test_resume_pending_creates_only_resume_capability_and_notifies_once(self):
        self.app.dependency_overrides[verify_token] = lambda: True
        create = MagicMock(side_effect=[True, False])
        notify = AsyncMock(return_value=True)
        with (
            patch(
                "app.api.v1.endpoints.approvals.create_pending_approval_once",
                create,
            ),
            patch(
                "app.api.v1.endpoints.approvals.send_user_notification",
                notify,
            ),
        ):
            first = self._request("POST", "/api/v1/approvals/test-resume-pending")
            duplicate = self._request("POST", "/api/v1/approvals/test-resume-pending")
        self.app.dependency_overrides.clear()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(first.json()["created"])
        self.assertFalse(duplicate.json()["created"])
        self.assertTrue(first.json()["notification_sent"])
        self.assertFalse(duplicate.json()["notification_sent"])
        notify.assert_awaited_once_with(NotificationType.APPROVAL_REQUIRED)
        create.assert_called_with(
            capability_key=approval_lock.TEST_APPROVAL_RESUME_CAPABILITY_KEY,
            action_type=approval_lock.TEST_APPROVAL_RESUME_ACTION_TYPE,
            step_summary=approval_lock.TEST_APPROVAL_RESUME_STEP_SUMMARY,
            ttl_minutes=10,
        )

        allowed_keys = {"ok", "created", "notification_sent", "status", "message"}
        self.assertEqual(set(first.json()), allowed_keys)
        self.assertEqual(set(duplicate.json()), allowed_keys)
        for payload in (first.json(), duplicate.json()):
            self.assertNotIn("approval_challenge", payload)
            self.assertNotIn("action_hash", payload)
            self.assertNotIn("pending_id", payload)
            self.assertNotIn("grant_id", payload)
            self.assertNotIn("token", payload)
            self.assertNotIn("secret", payload)

    def test_test_resume_run_consumes_only_harmless_test_grant(self):
        self.app.dependency_overrides[verify_token] = lambda: True
        consume = MagicMock(side_effect=[True, False])
        notify = AsyncMock(return_value=True)
        with (
            patch(
                "app.api.v1.endpoints.approvals.consume_test_approval_resume_grant",
                consume,
            ),
            patch(
                "app.api.v1.endpoints.approvals.send_user_notification",
                notify,
            ),
        ):
            resumed = self._request("POST", "/api/v1/approvals/test-resume-run")
            missing = self._request("POST", "/api/v1/approvals/test-resume-run")
        self.app.dependency_overrides.clear()

        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertTrue(resumed.json()["resumed"])
        self.assertFalse(missing.json()["resumed"])
        consume.assert_called()
        notify.assert_not_awaited()
        allowed_keys = {"ok", "resumed", "status", "message"}
        self.assertEqual(set(resumed.json()), allowed_keys)
        self.assertEqual(set(missing.json()), allowed_keys)
        for payload in (resumed.json(), missing.json()):
            self.assertNotIn("approval_challenge", payload)
            self.assertNotIn("action_hash", payload)
            self.assertNotIn("pending_id", payload)
            self.assertNotIn("grant_id", payload)
            self.assertNotIn("token", payload)
            self.assertNotIn("secret", payload)

    def test_helper_sanitizes_and_binds_limit(self):
        now = datetime.now(timezone.utc)
        rows = [
            (
                uuid.uuid4(),
                "capability.send_email",
                {
                    "step_summary": "Send the reviewed email",
                    "request_body": {"token": "secret-value", "content": "body"},
                    "headers": {"Authorization": "Bearer x"},
                    "nested": [{"api_key": "abc123"}],
                },
                now,
                now + timedelta(minutes=10),
                "awaiting",
            )
        ]
        connection = _Connection(rows)

        with patch.object(approval_lock, "_connect", return_value=connection):
            pending = approval_lock.list_active_pending_approvals(limit=999)

        self.assertEqual(len(connection.cursor_instance.statements), 1)
        _, params = connection.cursor_instance.statements[0]
        self.assertEqual(params, (20,))
        self.assertEqual(len(pending), 1)
        self.assertNotIn("approval_challenge", pending[0])
        self.assertNotIn("action_hash", pending[0])
        self.assertEqual(pending[0]["pending_id"], str(rows[0][0]))
        self.assertEqual(pending[0]["status"], "awaiting")
        self.assertEqual(
            pending[0]["action_snapshot"]["request_body"],
            "[REDACTED]",
        )
        self.assertEqual(
            pending[0]["action_snapshot"]["headers"],
            "[REDACTED]",
        )
        self.assertEqual(
            pending[0]["action_snapshot"]["nested"][0]["api_key"],
            "[REDACTED]",
        )

    def test_endpoint_returns_sanitized_items(self):
        now = datetime.now(timezone.utc)
        pending_rows = [
            {
                "pending_id": str(uuid.uuid4()),
                "capability_key": "capability.send_email",
                "action_snapshot": {"step_summary": "Approve send", "request_body": "[REDACTED]"},
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "status": "awaiting",
            }
        ]
        self.app.dependency_overrides[verify_token] = lambda: True
        with patch(
            "app.api.v1.endpoints.approvals.list_active_pending_approvals",
            return_value=pending_rows,
        ):
            response = self._request("GET", "/api/v1/approvals/pending")
        self.app.dependency_overrides.clear()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["pending_approvals"], pending_rows)


if __name__ == "__main__":
    unittest.main()
