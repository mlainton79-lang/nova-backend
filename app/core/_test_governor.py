#!/usr/bin/env python3
"""Unit tests for app.core.governor.evaluate_action.

Invokable directly, no pytest dependency:
    /usr/bin/python3 app/core/_test_governor.py

Each test stubs out app.observability so _emit_decision can run without
a database connection. Pure tests on the classifier + policy.

Exit 0 if all tests pass, 1 otherwise.

These tests pin the contract Codex called out in
nova-docs/ops/reviews/2026-06-02/codex-review-governor-destructive-gate.md:
the new internal_write opt-in path must not erase the old external_effect
opt-OUT behaviour. They're the structural guardrail against accidentally
breaking either side of the dual-meaning approval_required field.
"""

import os
import sys
import unittest.mock

# Make app.* imports work when invoked directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Stub psycopg2 + observability so the governor module loads without a DB.
sys.modules.setdefault("psycopg2", unittest.mock.MagicMock())
sys.modules.setdefault("psycopg2.extras", unittest.mock.MagicMock())
sys.modules.setdefault("app.observability", unittest.mock.MagicMock())

from app.core.governor import (  # noqa: E402
    classify_capability,
    evaluate_action,
    READ_ONLY,
    INTERNAL_WRITE,
    EXTERNAL_EFFECT,
    SELF_MODIFY,
)


results = []


def _check(label: str, got, want):
    ok = got == want
    results.append((label, ok, got, want))
    status = "PASS" if ok else "FAIL"
    print(f"  {status}  {label}")
    if not ok:
        print(f"        want: {want!r}")
        print(f"        got:  {got!r}")
    return ok


def assert_decision(label: str, cap, approval_token, **expected):
    """Run evaluate_action and assert all expected fields match."""
    d = evaluate_action(cap, approval_token=approval_token)
    all_ok = True
    for k, v in expected.items():
        if not _check(f"{label} :: {k}", d.get(k), v):
            all_ok = False
    return all_ok


# ── Test cases ──────────────────────────────────────────────────────────


def test_classification():
    """The classifier should route capabilities to the right action class
    before the policy layer is even invoked. Pin the priority order."""
    print("\n# classify_capability priority order")

    _check(
        "read_only when risk=low + no external_effect",
        classify_capability({"capability_key": "x", "risk_level": "low", "external_effect": False}),
        READ_ONLY,
    )
    _check(
        "internal_write when risk=medium + no external_effect",
        classify_capability({"capability_key": "x", "risk_level": "medium", "external_effect": False}),
        INTERNAL_WRITE,
    )
    _check(
        "external_effect when external_effect=True overrides risk",
        classify_capability({"capability_key": "x", "risk_level": "low", "external_effect": True}),
        EXTERNAL_EFFECT,
    )
    _check(
        "self_modify when capability_key has the marker, regardless of class fields",
        classify_capability({"capability_key": "code_edit_python_backend", "risk_level": "low", "external_effect": False}),
        SELF_MODIFY,
    )


def test_read_only_allowed():
    """READ_ONLY capabilities always allow, no token needed."""
    print("\n# read_only allow path")
    assert_decision(
        "read_only no token",
        cap={"capability_key": "memory_recall", "risk_level": "low", "external_effect": False},
        approval_token=None,
        allowed=True,
        reason="class_does_not_require_approval",
        approval_satisfied=False,
    )


def test_internal_write_opt_in_off_allowed():
    """Codex case 1: internal_write + approval_required=False allows
    without a token. The default for internal_write capabilities is
    auto-allow — preserves backward compat."""
    print("\n# Codex case 1: internal_write opt-in OFF → allow")
    assert_decision(
        "no approval_required field",
        cap={"capability_key": "x", "risk_level": "medium", "external_effect": False},
        approval_token=None,
        allowed=True,
        action_class=INTERNAL_WRITE,
        reason="class_does_not_require_approval",
    )
    assert_decision(
        "approval_required=False explicit",
        cap={"capability_key": "x", "risk_level": "medium", "external_effect": False, "approval_required": False},
        approval_token=None,
        allowed=True,
        action_class=INTERNAL_WRITE,
        reason="class_does_not_require_approval",
    )


def test_internal_write_opt_in_on_no_token_denied():
    """Codex case 2: internal_write + approval_required=True denies
    without a token. THE structural fix shipped 2026-06-02 — closes the
    vinted_draft_archive incident gap."""
    print("\n# Codex case 2: internal_write opt-in ON + no token → DENY")
    assert_decision(
        "vinted_draft_archive shape, no token",
        cap={"capability_key": "vinted_draft_archive", "risk_level": "medium", "external_effect": False, "approval_required": True},
        approval_token=None,
        allowed=False,
        action_class=INTERNAL_WRITE,
        reason="internal_write_approval_required_but_not_provided",
        approval_source="registry_opt_in",
        approval_satisfied=False,
    )


def test_internal_write_opt_in_on_with_token_allowed():
    """Codex case 3: internal_write + approval_required=True allows
    when a non-empty token is supplied."""
    print("\n# Codex case 3: internal_write opt-in ON + token → ALLOW")
    assert_decision(
        "vinted_draft_archive shape, with token",
        cap={"capability_key": "vinted_draft_archive", "risk_level": "medium", "external_effect": False, "approval_required": True},
        approval_token="matthew-approved",
        allowed=True,
        action_class=INTERNAL_WRITE,
        reason="approval_token_present",
        approval_source="registry_opt_in",
        approval_satisfied=True,
    )


def test_external_effect_pre_approved():
    """Codex case 4: external_effect + approval_required=False remains
    pre-greenlit (allow). This is the existing opt-OUT semantics and
    must NOT regress when the internal_write opt-in was added — they
    use the same field with opposite intent per class."""
    print("\n# Codex case 4: external_effect pre-greenlit → ALLOW")
    assert_decision(
        "pre-greenlit external action, no token",
        cap={"capability_key": "x", "risk_level": "low", "external_effect": True, "approval_required": False},
        approval_token=None,
        allowed=True,
        action_class=EXTERNAL_EFFECT,
        reason="pre_approved_at_registration",
        approval_source="class_gate",
        approval_satisfied=True,
    )


def test_external_effect_default_deny():
    """Codex case 5: external_effect + approval_required=True denies
    without a token. Existing behaviour, here as a regression pin."""
    print("\n# Codex case 5: external_effect default-deny")
    assert_decision(
        "gmail_send shape, no token",
        cap={"capability_key": "gmail_send", "risk_level": "medium", "external_effect": True, "approval_required": True},
        approval_token=None,
        allowed=False,
        action_class=EXTERNAL_EFFECT,
        reason="approval_required_but_not_provided",
        approval_source="class_gate",
        approval_satisfied=False,
    )


def test_external_effect_with_token_allowed():
    """Mirror of case 5: external_effect + approval_required=True +
    token allows. Not in Codex's explicit list but a natural completion
    — confirms the token unlocks the class-gated path the same way it
    unlocks the registry_opt_in path."""
    print("\n# Mirror: external_effect + token → ALLOW")
    assert_decision(
        "gmail_send shape, with token",
        cap={"capability_key": "gmail_send", "risk_level": "medium", "external_effect": True, "approval_required": True},
        approval_token="matthew-approved",
        allowed=True,
        action_class=EXTERNAL_EFFECT,
        reason="approval_token_present",
        approval_source="class_gate",
        approval_satisfied=True,
    )


def test_self_modify_default_deny():
    """SELF_MODIFY is in APPROVAL_REQUIRED_CLASSES — same gate as
    external_effect. Capability_key marker (e.g. 'code_edit_') flips
    classification regardless of registry flags."""
    print("\n# self_modify default-deny")
    assert_decision(
        "code_edit_ marker default-denies",
        cap={"capability_key": "code_edit_python_backend", "risk_level": "high", "external_effect": False, "approval_required": True},
        approval_token=None,
        allowed=False,
        action_class=SELF_MODIFY,
        reason="approval_required_but_not_provided",
        approval_source="class_gate",
    )


def test_kill_switch_off_allows_everything():
    """When GOVERNOR_ENABLED=false the governor returns allow=True for
    every action regardless of class. Clean rollback path. Sets
    reason='governor_disabled' so callers can log the override
    explicitly."""
    print("\n# kill-switch: GOVERNOR_ENABLED=false → allow all")
    prior = os.environ.get("GOVERNOR_ENABLED")
    try:
        os.environ["GOVERNOR_ENABLED"] = "false"
        assert_decision(
            "internal_write opt-in WOULD deny, but kill-switch overrides",
            cap={"capability_key": "vinted_draft_archive", "risk_level": "medium", "external_effect": False, "approval_required": True},
            approval_token=None,
            allowed=True,
            reason="governor_disabled",
        )
        assert_decision(
            "external_effect WOULD deny, but kill-switch overrides",
            cap={"capability_key": "gmail_send", "risk_level": "medium", "external_effect": True, "approval_required": True},
            approval_token=None,
            allowed=True,
            reason="governor_disabled",
        )
    finally:
        if prior is None:
            os.environ.pop("GOVERNOR_ENABLED", None)
        else:
            os.environ["GOVERNOR_ENABLED"] = prior


def test_empty_or_whitespace_token_not_satisfied():
    """An empty / whitespace approval_token must NOT satisfy approval.
    Guards against an accidental `approval_token=''` from a caller
    bypassing the gate."""
    print("\n# empty/whitespace token rejected")
    for tok in ("", "   ", "\t\n"):
        assert_decision(
            f"vinted_draft_archive with token={tok!r}",
            cap={"capability_key": "vinted_draft_archive", "risk_level": "medium", "external_effect": False, "approval_required": True},
            approval_token=tok,
            allowed=False,
            reason="internal_write_approval_required_but_not_provided",
        )


def test_non_dict_input_safe_default():
    """A non-dict capability input must NOT crash the governor — it
    falls back to READ_ONLY (the safest allow). _emit_decision is
    stubbed so this only exercises the classifier + policy."""
    print("\n# non-dict capability → safe read_only allow")
    assert_decision(
        "None capability",
        cap=None,
        approval_token=None,
        allowed=True,
        action_class=READ_ONLY,
    )


# ── Runner ──────────────────────────────────────────────────────────────


def main():
    test_classification()
    test_read_only_allowed()
    test_internal_write_opt_in_off_allowed()
    test_internal_write_opt_in_on_no_token_denied()
    test_internal_write_opt_in_on_with_token_allowed()
    test_external_effect_pre_approved()
    test_external_effect_default_deny()
    test_external_effect_with_token_allowed()
    test_self_modify_default_deny()
    test_kill_switch_off_allows_everything()
    test_empty_or_whitespace_token_not_satisfied()
    test_non_dict_input_safe_default()

    total = len(results)
    passed = sum(1 for _, ok, _, _ in results if ok)
    failed = total - passed
    print()
    print("=" * 60)
    print(f"governor unit tests: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
