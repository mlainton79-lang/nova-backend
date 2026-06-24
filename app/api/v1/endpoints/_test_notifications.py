import asyncio

import pytest

from app.api.v1.endpoints import notifications
from app.core import user_notifications
from app.core.user_notifications import NotificationType


def test_allowed_notification_resolves_to_safe_defaults():
    content = user_notifications.resolve_notification("approval_required")

    assert content.type is NotificationType.APPROVAL_REQUIRED
    assert content.title == "Nova approval needed"
    assert content.body == "Nova needs your approval before continuing."


def test_unknown_notification_type_is_rejected():
    with pytest.raises(ValueError, match="Unsupported notification type"):
        user_notifications.resolve_notification("unknown")


def test_gateway_sends_exactly_once(monkeypatch):
    calls = []

    async def fake_send(title, body, data=None):
        calls.append((title, body, data))
        return True

    monkeypatch.setattr(user_notifications, "send_push", fake_send)

    result = asyncio.run(
        user_notifications.send_user_notification(NotificationType.TASK_COMPLETE)
    )

    assert result is True
    assert calls == [
        (
            "Nova task complete",
            "Your Nova task completed successfully.",
            {"notification_type": "task_complete"},
        )
    ]


def test_endpoint_sends_once_and_returns_sanitized_response(monkeypatch):
    calls = []

    async def fake_send(notification_type):
        calls.append(notification_type)
        return True

    monkeypatch.setattr(notifications, "send_user_notification", fake_send)

    result = asyncio.run(
        notifications.test_latest_notification(
            notifications.TestNotificationRequest(type="summary_ready")
        )
    )

    assert calls == [NotificationType.SUMMARY_READY]
    assert result == {
        "ok": True,
        "status": "sent",
        "type": "summary_ready",
        "message": "Notification sent",
    }
    assert all("token" not in key.lower() for key in result)


def test_endpoint_defaults_to_approval_required(monkeypatch):
    calls = []

    async def fake_send(notification_type):
        calls.append(notification_type)
        return True

    monkeypatch.setattr(notifications, "send_user_notification", fake_send)

    result = asyncio.run(notifications.test_latest_notification())

    assert calls == [NotificationType.APPROVAL_REQUIRED]
    assert result["type"] == "approval_required"
