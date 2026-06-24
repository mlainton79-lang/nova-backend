"""Typed user notification gateway built on the existing FCM sender."""

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.push_notifications import send_push


class NotificationType(str, Enum):
    APPROVAL_REQUIRED = "approval_required"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"
    IMPORTANT_ALERT = "important_alert"
    SUMMARY_READY = "summary_ready"


@dataclass(frozen=True)
class NotificationContent:
    type: NotificationType
    title: str
    body: str


_DEFAULT_NOTIFICATIONS: Final[dict[NotificationType, NotificationContent]] = {
    NotificationType.APPROVAL_REQUIRED: NotificationContent(
        type=NotificationType.APPROVAL_REQUIRED,
        title="Nova approval needed",
        body="Nova needs your approval before continuing.",
    ),
    NotificationType.TASK_COMPLETE: NotificationContent(
        type=NotificationType.TASK_COMPLETE,
        title="Nova task complete",
        body="Your Nova task completed successfully.",
    ),
    NotificationType.TASK_FAILED: NotificationContent(
        type=NotificationType.TASK_FAILED,
        title="Nova task failed",
        body="Nova could not complete a task. Open Nova for details.",
    ),
    NotificationType.IMPORTANT_ALERT: NotificationContent(
        type=NotificationType.IMPORTANT_ALERT,
        title="Important Nova alert",
        body="Nova has an important update for you.",
    ),
    NotificationType.SUMMARY_READY: NotificationContent(
        type=NotificationType.SUMMARY_READY,
        title="Nova summary ready",
        body="Your Nova summary is ready to review.",
    ),
}


def resolve_notification(
    notification_type: NotificationType | str,
) -> NotificationContent:
    """Resolve an allowed notification type to its safe default content."""
    try:
        resolved_type = NotificationType(notification_type)
    except ValueError as error:
        raise ValueError("Unsupported notification type") from error
    return _DEFAULT_NOTIFICATIONS[resolved_type]


async def send_user_notification(
    notification_type: NotificationType | str = NotificationType.APPROVAL_REQUIRED,
) -> bool:
    """Send one typed notification to the latest registered device."""
    notification = resolve_notification(notification_type)
    return await send_push(
        notification.title,
        notification.body,
        data={"notification_type": notification.type.value},
    )
