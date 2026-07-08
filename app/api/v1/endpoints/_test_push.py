import asyncio
import os
import sys

HERE = os.path.dirname(__file__)
sys.path = [p for p in sys.path if os.path.abspath(p or ".") != os.path.abspath(HERE)]
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))

from fastapi import HTTPException

from app.api.v1.endpoints import push
from app.api.v1.endpoints.push import _resolve_push_registration


def test_query_registration_stays_compatible():
    result = _resolve_push_registration("query-value", "android", {})
    assert result == ("query-value", "android")


def test_android_json_registration_ignores_extra_fields():
    result = _resolve_push_registration(
        None,
        None,
        {
            "token": "body-value",
            "platform": "android",
            "app_package": "com.mlainton.nova",
            "source": "nova_android",
            "device_model": "test-device",
            "sdk_int": 34,
            "app_version": "1.0",
        },
    )
    assert result == ("body-value", "android")


def test_query_values_take_precedence_over_body():
    result = _resolve_push_registration(
        "query-value",
        "query-platform",
        {"token": "body-value", "platform": "body-platform"},
    )
    assert result == ("query-value", "query-platform")


def test_missing_or_blank_token_is_rejected():
    for value in (None, "", "   "):
        try:
            _resolve_push_registration(None, None, {"token": value})
        except HTTPException as error:
            assert error.status_code == 422
        else:
            raise AssertionError("Expected a validation error")


def test_platform_defaults_to_android():
    result = _resolve_push_registration(None, None, {"token": "body-value"})
    assert result == ("body-value", "android")


def test_latest_push_sends_one_fixed_notification(monkeypatch):
    calls = []

    monkeypatch.setattr(push, "get_push_token", lambda: "registered")

    async def fake_send(notification_type):
        calls.append(notification_type)
        return True

    monkeypatch.setattr(push, "send_user_notification", fake_send)

    result = asyncio.run(push.test_latest_push())

    assert calls == [push.NotificationType.IMPORTANT_ALERT]
    assert result == {
        "ok": True,
        "status": "sent",
        "message": "Test notification sent",
    }


def test_latest_push_does_not_send_without_token(monkeypatch):
    monkeypatch.setattr(push, "get_push_token", lambda: None)

    async def unexpected_send(notification_type):
        raise AssertionError("send_push must not be called without a token")

    monkeypatch.setattr(push, "send_user_notification", unexpected_send)

    result = asyncio.run(push.test_latest_push())

    assert result["ok"] is False
    assert result["status"] == "no_token"
