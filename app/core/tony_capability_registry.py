"""Tony capability truth registry v1.

This module is metadata only. It gives Tony one safe, code-owned set of
user-facing capability cards for describing what Nova can do, what is limited,
and what remains blocked. It does not call integrations, create approvals,
touch storage, send notifications, or execute work.
"""
from dataclasses import dataclass
from types import MappingProxyType


AVAILABLE = "available"
LIMITED = "limited"
APPROVAL_REQUIRED = "approval_required"
DESIGN_ONLY = "design_only"
BLOCKED = "blocked"
TEST_ONLY = "test_only"

CAPABILITY_STATES = (
    AVAILABLE,
    LIMITED,
    APPROVAL_REQUIRED,
    DESIGN_ONLY,
    BLOCKED,
    TEST_ONLY,
)


@dataclass(frozen=True)
class TonyCapabilityCard:
    """User-facing truth card for one Tony/Nova ability."""

    key: str
    state: str
    title: str
    user_facing_summary: str
    safe_to_say: str
    limits: tuple[str, ...]


def _card(
    key: str,
    state: str,
    title: str,
    user_facing_summary: str,
    safe_to_say: str,
    limits: tuple[str, ...],
) -> TonyCapabilityCard:
    if state not in CAPABILITY_STATES:
        raise ValueError("unknown_capability_state")
    if not limits:
        raise ValueError("capability_limits_required")
    return TonyCapabilityCard(
        key=key,
        state=state,
        title=title,
        user_facing_summary=user_facing_summary,
        safe_to_say=safe_to_say,
        limits=limits,
    )


_CARDS = (
    _card(
        "chat.answer",
        AVAILABLE,
        "Answer questions",
        "Tony can answer questions, reason through choices, and draft text.",
        "I can help think this through and draft a clear answer.",
        (
            "May be wrong and should not be treated as final professional advice.",
            "Cannot guarantee that fast-changing facts are current unless checked.",
            "No external action is taken: no account change, message send, purchase, or deployment.",
        ),
    ),
    _card(
        "memory.recall",
        LIMITED,
        "Use Nova memory",
        "Tony can use saved Nova memory to keep context across conversations.",
        "I can use remembered context where it helps, and keep the answer grounded.",
        (
            "Memory may be incomplete or out of date.",
            "Private raw records should not be exposed in ordinary replies.",
            "Destructive memory changes need separate review.",
        ),
    ),
    _card(
        "memory.save_low_risk",
        AVAILABLE,
        "Save low-risk memory",
        "Tony can save low-risk internal facts for future context.",
        "I can remember low-risk details that make future answers more useful.",
        (
            "No external system is changed.",
            "Sensitive, credential-like, or risky material should not be saved as ordinary memory.",
            "This is not a general database editing ability.",
        ),
    ),
    _card(
        "briefing.today",
        LIMITED,
        "Show today's focus",
        "Tony can assemble a daily focus view with briefing text, next actions, approvals, health flags, and recent activity.",
        "I can show what needs attention now and suggest the next practical steps.",
        (
            "Only as accurate as the connected signals and latest syncs.",
            "Read-only summary; it does not send messages, approve actions, deploy code, or mutate external accounts.",
            "Live integration failures should be surfaced as flags rather than hidden.",
        ),
    ),
    _card(
        "review.daily",
        LIMITED,
        "Review the day",
        "Tony can summarise today's activity and carry forward follow-up actions.",
        "I can give you an end-of-day review with the Nova runs, urgent items, and follow-ups that need carrying forward.",
        (
            "Only includes signals Nova can read from its current stores and integrations.",
            "Read-only summary; it does not close tasks, send messages, or change external systems.",
            "Quiet or partially synced days may produce a short or incomplete review.",
        ),
    ),
    _card(
        "gmail.review_and_draft",
        APPROVAL_REQUIRED,
        "Review email and prepare drafts",
        "Tony can help review email context and prepare draft wording.",
        "I can prepare draft wording for you to review before anything leaves Gmail.",
        (
            "Tony must not send email without Matthew approval.",
            "Deleting, archiving, forwarding, attachments, and broad mailbox changes are not covered by this card.",
            "Draft creation is limited to exact reviewed fields when a dedicated runner is connected.",
        ),
    ),
    _card(
        "calendar.plan",
        APPROVAL_REQUIRED,
        "Plan calendar changes",
        "Tony can help plan calendar entries and changes.",
        "I can prepare the calendar change for review before it touches the calendar.",
        (
            "Creating, updating, or deleting live calendar events requires approval.",
            "No recurring-event or invite change should be implied unless explicitly reviewed.",
            "This card is for planning and review, not autonomous calendar mutation.",
        ),
    ),
    _card(
        "selling.draft_listing",
        LIMITED,
        "Prepare selling drafts",
        "Tony can help prepare local selling-listing drafts for review.",
        "I can help turn item details into a local listing draft for you to check.",
        (
            "Does not post marketplace listings.",
            "Does not message buyers, accept offers, buy postage, or handle orders.",
            "Real account automation and live price changes are outside this card.",
        ),
    ),
    _card(
        "notifications.urgent",
        LIMITED,
        "Send limited urgent notifications",
        "Tony can use narrow notification paths for urgent or approval-related alerts.",
        "I can nudge you when a narrow notification rule says it is worth interrupting you.",
        (
            "Non-approval urgent notifications need conservative rules.",
            "Notifications must not expose private payloads or credentials.",
            "This is not permission to spam or bypass approval review.",
        ),
    ),
    _card(
        "code.review_local",
        LIMITED,
        "Review local code",
        "Tony can inspect local repo code and suggest or make scoped local edits when asked.",
        "I can review the local code and make scoped changes inside the approved files.",
        (
            "Deploying, pushing, or changing production state needs explicit scope.",
            "Credential-bearing files and shell startup files are not part of ordinary code review.",
            "Reviews should report risks without exposing credentials or private payloads.",
        ),
    ),
    _card(
        "external_actions.approval_lock",
        APPROVAL_REQUIRED,
        "Prepare approval-gated external actions",
        "Tony can prepare clearly described external actions for Matthew to review.",
        "I can prepare a precise approval request, then wait for your explicit go-ahead.",
        (
            "Approval must describe the exact reviewed action.",
            "Approval records are not permission to run arbitrary actions.",
            "Payment, order handling, and real account automation need separate explicit unlocks.",
        ),
    ),
    _card(
        "marketplace.live_account_actions",
        BLOCKED,
        "Live marketplace account actions",
        "Posting, buyer messaging, offers, live price changes, postage, and order handling are blocked by default.",
        "I cannot take live marketplace actions unless Matthew explicitly unlocks a narrow reviewed capability.",
        (
            "No autonomous posting, buyer messaging, offer acceptance, price changes, postage purchase, or order handling.",
            "No browser automation against real marketplace accounts from this card.",
            "Use local draft preparation or approved APIs only where separately allowed.",
        ),
    ),
    _card(
        "banking.money_movement",
        BLOCKED,
        "Banking and money movement",
        "Payments, transfers, and other money movement are blocked.",
        "I cannot move money or make payments.",
        (
            "No bank transfer, card payment, marketplace payout handling, or financial commitment.",
            "Financial analysis is separate from taking financial action.",
            "A future capability would need a dedicated approval and verification design.",
        ),
    ),
    _card(
        "test.noop_approval",
        TEST_ONLY,
        "Test approval no-op",
        "Internal tests can exercise the approval path with harmless no-op actions.",
        "The test path proves the approval plumbing without touching external systems.",
        (
            "Only test capability keys are covered.",
            "No external account, notification, payment, marketplace, or email action is performed.",
            "Must never become a generic action dispatcher.",
        ),
    ),
)

TONY_CAPABILITY_CARDS = MappingProxyType({card.key: card for card in _CARDS})


def list_tony_capability_cards() -> tuple[TonyCapabilityCard, ...]:
    """Return all user-facing capability cards sorted by stable key."""
    return tuple(TONY_CAPABILITY_CARDS[key] for key in sorted(TONY_CAPABILITY_CARDS))


def get_tony_capability_card(key: str) -> TonyCapabilityCard | None:
    """Return one capability card, or None for an unknown key."""
    return TONY_CAPABILITY_CARDS.get(key)


def list_tony_capability_cards_by_state(
    state: str,
) -> tuple[TonyCapabilityCard, ...]:
    """Return capability cards in one stable state."""
    if state not in CAPABILITY_STATES:
        raise ValueError("unknown_capability_state")
    return tuple(
        card for card in list_tony_capability_cards() if card.state == state
    )
