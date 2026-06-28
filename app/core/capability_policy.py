"""Tony Green-Amber-Red Capability Policy Matrix v1.

This module is a read-only policy inventory. It does not enforce runtime
behaviour, create approvals, send notifications, call integrations, import
workers, or touch the database. The goal is one canonical classification that
planner, endpoint, prompt, Android, and worker work can align to later.
"""
from dataclasses import dataclass
from types import MappingProxyType


GREEN = "green"
AMBER = "amber"
RED = "red"
TEST_ONLY = "test_only"

AUTONOMY_CLASSES = (GREEN, AMBER, RED, TEST_ONLY)


@dataclass(frozen=True)
class CapabilityPolicy:
    """Read-only autonomy policy for one capability or runtime surface."""

    key: str
    autonomy_class: str
    human_name: str
    risk_notes: str
    external_action: bool
    connected: bool
    approval_required: bool
    current_runtime_surface: str
    recommended_next_state: str


def _policy(
    key: str,
    autonomy_class: str,
    human_name: str,
    risk_notes: str,
    external_action: bool,
    connected: bool,
    approval_required: bool,
    current_runtime_surface: str,
    recommended_next_state: str,
) -> CapabilityPolicy:
    if autonomy_class not in AUTONOMY_CLASSES:
        raise ValueError("unknown_autonomy_class")
    return CapabilityPolicy(
        key=key,
        autonomy_class=autonomy_class,
        human_name=human_name,
        risk_notes=risk_notes,
        external_action=external_action,
        connected=connected,
        approval_required=approval_required,
        current_runtime_surface=current_runtime_surface,
        recommended_next_state=recommended_next_state,
    )


_POLICIES = (
    _policy(
        "chat.local_reasoning",
        GREEN,
        "Local reasoning and response drafting",
        "No external write, payment, account mutation, posting, messaging, browser automation, or destructive action.",
        False,
        True,
        False,
        "chat/council/local reasoning surfaces",
        "Keep autonomous with fabrication and retrieval guards.",
    ),
    _policy(
        "memory.read",
        GREEN,
        "Read Nova memory",
        "Read-only access to Tony/Nova memory context.",
        False,
        True,
        False,
        "memory recall and prompt context",
        "Keep autonomous; avoid exposing raw private rows.",
    ),
    _policy(
        "memory.low_risk_save",
        GREEN,
        "Save low-risk memory",
        "Internal low-risk memory write with no external consequence.",
        False,
        True,
        False,
        "memory/facts save paths",
        "Keep autonomous for low-risk facts; review destructive memory edits separately.",
    ),
    _policy(
        "drafts.review",
        GREEN,
        "Review existing drafts",
        "Read-only review of prepared content.",
        False,
        True,
        False,
        "draft review/list endpoints and Android review screens",
        "Keep autonomous as read-only review.",
    ),
    _policy(
        "selling.draft_review",
        GREEN,
        "Review selling draft",
        "Read-only marketplace-neutral draft review.",
        False,
        True,
        False,
        "selling draft review/list helpers",
        "Keep autonomous while draft data stays local/internal.",
    ),
    _policy(
        "selling.draft_list",
        GREEN,
        "List selling drafts",
        "Read-only draft inventory view.",
        False,
        True,
        False,
        "selling draft list helpers and Android draft list",
        "Keep autonomous with sanitized projections.",
    ),
    _policy(
        "vinted.prepare_listing_draft_local",
        GREEN,
        "Prepare local Vinted listing draft",
        "Local/user-visible listing preparation only; no Vinted account access, posting, messaging, scraping, browser automation, or price mutation.",
        False,
        True,
        False,
        "photo/listing draft pipeline and Android draft review",
        "Promote to explicit manifest entry before any approval or marketplace edge.",
    ),
    _policy(
        "fcm.register_device",
        GREEN,
        "Register Android FCM device",
        "Device registration initiated by Android; no user-facing external consequence by itself.",
        False,
        True,
        False,
        "/push/register",
        "Keep autonomous but never expose registration material.",
    ),
    _policy(
        "approval.create_external_action_request",
        AMBER,
        "Create approval request for external action",
        "Creates a review item before an external consequence; must preserve exact reviewed fields.",
        False,
        True,
        True,
        "approval_lock create_pending_approval_once boundary",
        "Use only through capability-specific wrappers and sanitized snapshots.",
    ),
    _policy(
        "gmail.create_draft",
        AMBER,
        "Create Gmail draft",
        "Future external Gmail write; currently design-only and not connected.",
        True,
        False,
        True,
        "approved capability manifest and disabled Gmail draft plan",
        "First live Gmail approval request, then verified draft-only runner.",
    ),
    _policy(
        "gmail.legacy_send",
        AMBER,
        "Legacy Gmail send/reply",
        "Active legacy external email write code exists but should not be autonomous.",
        True,
        True,
        True,
        "legacy Gmail endpoints and planner branches",
        "Migrate behind Approval Inbox/grant contract before expanding.",
    ),
    _policy(
        "gmail.legacy_delete_or_trash",
        AMBER,
        "Legacy Gmail trash/delete",
        "External destructive email mutation; reversible trash and permanent delete paths exist.",
        True,
        True,
        True,
        "legacy Gmail trash/delete endpoints and planner branches",
        "Keep approval-gated; permanent delete needs stronger lock before use.",
    ),
    _policy(
        "calendar.write_update_delete",
        AMBER,
        "Calendar write/update/delete",
        "External calendar mutation code exists; not autonomous.",
        True,
        True,
        True,
        "calendar endpoints and planner branches",
        "Migrate to exact approval snapshots before live autonomy.",
    ),
    _policy(
        "selling.draft_archive",
        AMBER,
        "Archive selling draft",
        "Internal destructive but reversible draft mutation.",
        False,
        True,
        True,
        "selling draft archive planner branch",
        "Keep approval-gated because it removes drafts from active review.",
    ),
    _policy(
        "vinted.create_marketplace_job",
        AMBER,
        "Create Vinted marketplace job",
        "Creates a job that could lead to browser/account activity if a worker is invoked.",
        False,
        True,
        True,
        "/vinted/jobs",
        "Require explicit review and do not auto-run workers.",
    ),
    _policy(
        "vinted.worker_handoff",
        AMBER,
        "Hand off to Vinted worker",
        "Human-triggered transition toward high-risk browser automation.",
        True,
        True,
        True,
        "vinted_worker manual invocation path",
        "Keep disabled from planner; redesign behind strict approval before use.",
    ),
    _policy(
        "ebay.oauth_or_operator",
        AMBER,
        "eBay OAuth or operator",
        "External marketplace account connection/operator boundary.",
        True,
        True,
        True,
        "eBay OAuth endpoints and selling operator stub",
        "Keep approval-gated; no listing operator without manifest and verification.",
    ),
    _policy(
        "whatsapp.send_message",
        AMBER,
        "Send WhatsApp message",
        "External user messaging.",
        True,
        True,
        True,
        "WhatsApp endpoint/core module",
        "Require approval or narrow notification policy before proactive sends.",
    ),
    _policy(
        "notifications.non_approval_urgent",
        AMBER,
        "Non-approval urgent notification",
        "Interrupts Matthew; external push notification without approval-review semantics.",
        True,
        True,
        True,
        "typed notification gateway and urgent push gate",
        "Keep default-gated; only unlock with explicit urgency rules.",
    ),
    _policy(
        "code.self_modify_or_deploy",
        AMBER,
        "Self-modify or deploy code",
        "Changes Nova itself or production behaviour.",
        True,
        True,
        True,
        "builder, code intelligence, git/deploy workflows",
        "Require Matthew approval and review evidence for every change.",
    ),
    _policy(
        "vinted.post_listing",
        RED,
        "Post Vinted listing",
        "Public marketplace posting is not unlocked.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until Matthew explicitly unlocks a verified posting capability.",
    ),
    _policy(
        "vinted.browser_automation_autonomous",
        RED,
        "Autonomous Vinted browser automation",
        "Real account browser automation must not run autonomously.",
        True,
        True,
        True,
        "Vinted worker and Android WebView operator surfaces",
        "Refuse until a future explicit unlock, approval, and verification design.",
    ),
    _policy(
        "vinted.buyer_message",
        RED,
        "Message Vinted buyer",
        "Buyer communication has direct external user consequence.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until separate buyer-message capability exists.",
    ),
    _policy(
        "vinted.accept_offer",
        RED,
        "Accept Vinted offer",
        "Commits to a marketplace transaction.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until commerce/offer policy exists.",
    ),
    _policy(
        "vinted.change_live_price",
        RED,
        "Change live Vinted price",
        "Mutates a live marketplace listing.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until price-change approval and verification exist.",
    ),
    _policy(
        "vinted.buy_postage",
        RED,
        "Buy Vinted postage",
        "Financial/external order consequence.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until payments/postage policy exists.",
    ),
    _policy(
        "vinted.payment_or_order_handling",
        RED,
        "Handle Vinted payment or order",
        "Financial/order fulfilment consequence.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until commerce policy exists.",
    ),
    _policy(
        "marketplace.scraping",
        RED,
        "Marketplace scraping",
        "Scraping marketplace pages is not unlocked.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until reviewed; use approved APIs or user-provided data only.",
    ),
    _policy(
        "browser.real_account_automation_without_unlock",
        RED,
        "Real account browser automation without unlock",
        "Any real account automation without explicit unlock is blocked.",
        True,
        True,
        True,
        "browser/worker surfaces",
        "Refuse by default; require a specific approved capability.",
    ),
    _policy(
        "banking.payment_or_transfer",
        RED,
        "Bank payment or transfer",
        "Financial movement of money is not unlocked.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until a dedicated financial approval and verification model exists.",
    ),
    _policy(
        "gmail.send_without_approval",
        RED,
        "Send Gmail without approval",
        "Email send without Matthew approval is blocked.",
        True,
        False,
        True,
        "not allowed",
        "Refuse and route to exact approval snapshot first.",
    ),
    _policy(
        "gmail.delete_without_approval",
        RED,
        "Delete Gmail without approval",
        "Email deletion without Matthew approval is blocked.",
        True,
        False,
        True,
        "not allowed",
        "Refuse and route to exact approval snapshot first; permanent delete needs extra lock.",
    ),
    _policy(
        "calendar.write_without_approval",
        RED,
        "Write calendar without approval",
        "Calendar mutation without Matthew approval is blocked.",
        True,
        False,
        True,
        "not allowed",
        "Refuse and route to exact approval snapshot first.",
    ),
    _policy(
        "external_write_without_approval",
        RED,
        "External write without approval",
        "Catch-all for unapproved external consequences.",
        True,
        False,
        True,
        "global policy",
        "Refuse unless a narrower green/amber policy explicitly allows it.",
    ),
    _policy(
        "broad_self_expansion_without_matthew_approval",
        RED,
        "Broad self-expansion without approval",
        "Self-expansion changes Tony/Nova capabilities and risk profile.",
        True,
        False,
        True,
        "not allowed",
        "Refuse until Matthew approval, review, tests, commit, and deployment evidence exist.",
    ),
    _policy(
        "test.approval_resume",
        TEST_ONLY,
        "Test-only harmless approval-resume test",
        "Test-only approval-gated no-op; consumes only a matching safe test grant.",
        False,
        True,
        True,
        "explicit safe test resume endpoint",
        "Keep test-only; never generalize into arbitrary dispatcher.",
    ),
    _policy(
        "test.approved_noop",
        TEST_ONLY,
        "Test-only harmless approved no-op test",
        "Test-only approval-gated no-op; consumes only a matching safe test grant.",
        False,
        True,
        True,
        "explicit safe no-op endpoint",
        "Keep test-only; never generalize into arbitrary dispatcher.",
    ),
)

CAPABILITY_POLICY = MappingProxyType({policy.key: policy for policy in _POLICIES})


def list_capability_policy() -> tuple[CapabilityPolicy, ...]:
    """Return the full read-only policy matrix sorted by key."""
    return tuple(CAPABILITY_POLICY[key] for key in sorted(CAPABILITY_POLICY))


def get_capability_policy(key: str) -> CapabilityPolicy | None:
    """Return one policy entry, or None for an unclassified key."""
    return CAPABILITY_POLICY.get(key)


def classify_capability(key: str) -> str | None:
    """Return green/amber/red/test_only for a classified capability."""
    policy = get_capability_policy(key)
    return policy.autonomy_class if policy else None
