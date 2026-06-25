#!/usr/bin/env python3
"""Safety tests for non-approval urgent push notification gating."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("psycopg2", MagicMock())

from app.core import push_notifications, user_notifications  # noqa: E402
from app.core.user_notifications import NotificationType  # noqa: E402


class UrgentNotificationGateTests(unittest.TestCase):
    def test_approval_required_still_uses_direct_push_path(self):
        send = AsyncMock(return_value=True)
        with patch.object(user_notifications, "send_push", send):
            result = asyncio.run(
                user_notifications.send_user_notification(
                    NotificationType.APPROVAL_REQUIRED
                )
            )

        self.assertTrue(result)
        send.assert_awaited_once()
        title, body = send.await_args.args[:2]
        self.assertEqual(title, "Nova approval needed")
        self.assertIn("approval", body.lower())

    def test_important_alert_is_blocked_by_default_gate(self):
        urgent = AsyncMock(return_value=False)
        direct = AsyncMock(return_value=True)
        with (
            patch.object(user_notifications, "send_non_approval_urgent_push", urgent),
            patch.object(user_notifications, "send_push", direct),
        ):
            result = asyncio.run(
                user_notifications.send_user_notification(
                    NotificationType.IMPORTANT_ALERT
                )
            )

        self.assertFalse(result)
        urgent.assert_awaited_once()
        direct.assert_not_awaited()

    def test_tony_urgent_is_blocked_by_default_gate(self):
        send = AsyncMock(return_value=True)
        with (
            patch.object(push_notifications, "NON_APPROVAL_URGENT_PUSH_ENABLED", False),
            patch.object(push_notifications, "send_push", send),
        ):
            result = asyncio.run(
                push_notifications.tony_notify("safe synthetic message", "urgent")
            )

        self.assertFalse(result)
        send.assert_not_awaited()

    def test_tony_normal_notification_uses_existing_push_path(self):
        send = AsyncMock(return_value=True)
        with patch.object(push_notifications, "send_push", send):
            result = asyncio.run(
                push_notifications.tony_notify("safe synthetic message", "normal")
            )

        self.assertTrue(result)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[0], "Tony")

    def test_enabled_urgent_uses_cooldown_claim_before_send(self):
        send = AsyncMock(return_value=True)
        claims = MagicMock(side_effect=[True, False])
        with (
            patch.object(push_notifications, "NON_APPROVAL_URGENT_PUSH_ENABLED", True),
            patch.object(push_notifications, "_claim_non_approval_urgent_send", claims),
            patch.object(push_notifications, "send_push", send),
        ):
            first = asyncio.run(
                push_notifications.send_non_approval_urgent_push(
                    "Safe urgent title",
                    "safe synthetic body",
                    dedupe_key="test-key",
                )
            )
            duplicate = asyncio.run(
                push_notifications.send_non_approval_urgent_push(
                    "Safe urgent title",
                    "safe synthetic body",
                    dedupe_key="test-key",
                )
            )

        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertEqual(claims.call_count, 2)
        send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
