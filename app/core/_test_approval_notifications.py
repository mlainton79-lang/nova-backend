#!/usr/bin/env python3
"""Direct structural tests for deduplicated approval notifications."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("app.observability", MagicMock())

from app.core import approval_lock, plan_executor  # noqa: E402


class _Cursor:
    def __init__(self, inserted):
        self.inserted = inserted
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return ("created",) if self.inserted else None


class _Connection:
    def __init__(self, inserted):
        self.cursor_instance = _Cursor(inserted)
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.autocommit = True

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class ApprovalNotificationTests(unittest.TestCase):
    def test_first_approval_creates_pending_record(self):
        connection = _Connection(inserted=True)
        with patch.object(approval_lock, "_connect", return_value=connection):
            created = approval_lock.create_pending_approval_once(
                capability_key="gmail_send",
                action_type="external_effect",
                step_summary="Send the reviewed message",
            )

        self.assertTrue(created)
        self.assertTrue(connection.committed)
        self.assertEqual(len(connection.cursor_instance.statements), 2)

    def test_duplicate_approval_returns_false(self):
        connection = _Connection(inserted=False)
        with patch.object(approval_lock, "_connect", return_value=connection):
            created = approval_lock.create_pending_approval_once(
                capability_key="gmail_send",
                action_type="external_effect",
                step_summary="Send the reviewed message",
            )

        self.assertFalse(created)
        self.assertTrue(connection.committed)

    def test_duplicate_path_notifies_once(self):
        create = MagicMock(side_effect=[True, False])
        send = AsyncMock(return_value=True)
        approval_module = MagicMock(create_pending_approval_once=create)
        notification_module = MagicMock()
        notification_module.NotificationType.APPROVAL_REQUIRED = "approval_required"
        notification_module.send_user_notification = send
        step = {
            "required_capability": "gmail_send",
            "description": "Send the reviewed message",
            "registry_match": {"capability_key": "gmail_send"},
            "governor_decision": {"action_class": "external_effect"},
        }

        with patch.dict(
            sys.modules,
            {
                "app.core.approval_lock": approval_module,
                "app.core.user_notifications": notification_module,
            },
        ):
            asyncio.run(plan_executor._notify_pending_approval_once(step))
            asyncio.run(plan_executor._notify_pending_approval_once(step))

        self.assertEqual(send.await_count, 1)

    def test_notification_failure_keeps_execution_paused(self):
        approval_module = MagicMock(
            create_pending_approval_once=MagicMock(return_value=True)
        )
        notification_module = MagicMock()
        notification_module.NotificationType.APPROVAL_REQUIRED = "approval_required"
        notification_module.send_user_notification = AsyncMock(
            side_effect=RuntimeError("sanitized test failure")
        )
        plan = {
            "goal": "safe test",
            "steps": [
                {
                    "step_number": 1,
                    "status": "needs_approval",
                    "required_capability": "gmail_send",
                    "description": "Send the reviewed message",
                    "registry_match": {"capability_key": "gmail_send"},
                    "governor_decision": {"action_class": "external_effect"},
                }
            ],
        }

        with patch.dict(
            sys.modules,
            {
                "app.core.approval_lock": approval_module,
                "app.core.user_notifications": notification_module,
            },
        ):
            result = asyncio.run(plan_executor.execute_plan(plan))

        self.assertFalse(result["ok"])
        self.assertEqual(result["executed_count"], 0)
        self.assertEqual(result["paused_step"]["reason"], "needs_approval")


if __name__ == "__main__":
    unittest.main()
