#!/usr/bin/env python3
"""Unit tests for the destructive-name registry assertion in
app.core.capabilities.

Invokable directly, no pytest dependency:
    /usr/bin/python3 app/core/_test_capabilities_destructive_gate.py

These tests pin the convention Codex flagged in round 2 of the
2026-06-02 governor destructive-gate review: any capability whose
capability_key contains a destructive-verb token (delete / archive /
trash / purge / remove / drop) must declare external_effect=True or
approval_required=True. The assertion runs in register_capability AND
in update_capability so future destructive capabilities cannot silently
land ungated.

Stubs psycopg2 + app.observability so the pure helpers
(is_destructive_key, _assert_destructive_gated) can run without a DB.
The DB-touching helpers (register_capability, update_capability,
audit_destructive_gating) are tested via mocks to verify the assertion
fires at the right call site without needing a live DB.

Exit 0 if all tests pass, 1 otherwise.
"""

import os
import sys
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Stub heavy deps so we can import capabilities.py without a DB.
sys.modules.setdefault("psycopg2", unittest.mock.MagicMock())
sys.modules.setdefault("psycopg2.extras", unittest.mock.MagicMock())
sys.modules.setdefault("app.observability", unittest.mock.MagicMock())

from app.core import capabilities  # noqa: E402
from app.core.capabilities import (  # noqa: E402
    is_destructive_key,
    _assert_destructive_gated,
    _DESTRUCTIVE_VERB_TOKENS,
    _DESTRUCTIVE_GATING_ALLOWLIST,
)


results = []


def _check(label: str, got, want):
    ok = got == want
    results.append((label, ok))
    status = "PASS" if ok else "FAIL"
    print(f"  {status}  {label}")
    if not ok:
        print(f"        want: {want!r}")
        print(f"        got:  {got!r}")


def _check_raises(label: str, fn, *args, exc_type=ValueError, must_contain: str = ""):
    raised = None
    try:
        fn(*args)
    except Exception as e:
        raised = e
    if raised is None:
        results.append((label, False))
        print(f"  FAIL  {label} :: expected {exc_type.__name__}, got nothing")
        return
    if not isinstance(raised, exc_type):
        results.append((label, False))
        print(f"  FAIL  {label} :: expected {exc_type.__name__}, got {type(raised).__name__}: {raised}")
        return
    if must_contain and must_contain not in str(raised):
        results.append((label, False))
        print(f"  FAIL  {label} :: error missing {must_contain!r}: {raised}")
        return
    results.append((label, True))
    print(f"  PASS  {label}")


def _check_no_raise(label: str, fn, *args):
    try:
        fn(*args)
        results.append((label, True))
        print(f"  PASS  {label}")
    except Exception as e:
        results.append((label, False))
        print(f"  FAIL  {label} :: unexpectedly raised {type(e).__name__}: {e}")


# ── Test cases ──────────────────────────────────────────────────────────


def test_is_destructive_key_positive():
    """Token-based matching: every destructive verb in
    _DESTRUCTIVE_VERB_TOKENS triggers a True, both at the end of the
    key and in the middle."""
    print("\n# is_destructive_key — positive matches")
    for verb in sorted(_DESTRUCTIVE_VERB_TOKENS):
        _check(f"trailing token: foo_{verb}", is_destructive_key(f"foo_{verb}"), True)
        _check(f"middle token: foo_{verb}_bar", is_destructive_key(f"foo_{verb}_bar"), True)
        _check(f"leading token: {verb}_foo", is_destructive_key(f"{verb}_foo"), True)


def test_is_destructive_key_negative():
    """Non-destructive keys must NOT trigger. Common false-positive
    candidates: substring matches like 'dropdown' (contains 'drop'),
    'decoration' (contains 'delete' as substring? actually no — but
    'remove' isn't in 'remover_lib' either as a token). Token-based
    splitting prevents these."""
    print("\n# is_destructive_key — negative (false-positive guards)")
    for key in (
        "memory_recall",
        "gmail_send",
        "calendar_read",
        "vinted_draft_review",
        "dropdown_select",       # substring 'drop' inside 'dropdown' — not a token
        "decoration_apply",      # 'decor' isn't a verb token
        "trashcan_icon",         # substring 'trash' inside 'trashcan' — not a token
        "archiver_module",       # 'archiver' isn't 'archive' — different token
        "removable_panel",       # 'removable' isn't 'remove'
        "purger_helper",         # 'purger' isn't 'purge'
        "deleted_emails_view",   # 'deleted' isn't 'delete' — different token
        "",
    ):
        _check(f"non-destructive: {key!r}", is_destructive_key(key), False)


def test_is_destructive_key_edge_cases():
    """None and empty inputs return False (safe default)."""
    print("\n# is_destructive_key — edge cases")
    _check("None input", is_destructive_key(None), False)
    _check("empty string", is_destructive_key(""), False)
    _check("just underscores", is_destructive_key("___"), False)


def test_assert_passes_for_gated_destructive():
    """Destructive-keyed but gated capabilities should pass through
    the assertion. Mirrors the four live rows audited 2026-06-02."""
    print("\n# _assert_destructive_gated — gated rows pass")
    _check_no_raise(
        "vinted_draft_archive (approval_required=True)",
        _assert_destructive_gated, "vinted_draft_archive", False, True,
    )
    _check_no_raise(
        "gmail_delete (external_effect=True, approval_required=True)",
        _assert_destructive_gated, "gmail_delete", True, True,
    )
    _check_no_raise(
        "calendar_delete (external_effect=True)",
        _assert_destructive_gated, "calendar_delete", True, False,
    )
    _check_no_raise(
        "gmail_delete_permanent (both flags set)",
        _assert_destructive_gated, "gmail_delete_permanent", True, True,
    )


def test_assert_passes_for_non_destructive():
    """Non-destructive keys pass regardless of flags."""
    print("\n# _assert_destructive_gated — non-destructive keys pass")
    _check_no_raise(
        "memory_recall, both flags False",
        _assert_destructive_gated, "memory_recall", False, False,
    )
    _check_no_raise(
        "vinted_draft_create, both flags False",
        _assert_destructive_gated, "vinted_draft_create", False, False,
    )
    _check_no_raise(
        "dropdown_select (false-positive guard)",
        _assert_destructive_gated, "dropdown_select", False, False,
    )


def test_assert_fails_for_ungated_destructive():
    """The whole point: destructive-keyed AND neither flag set must
    raise with a guidance-rich error message."""
    print("\n# _assert_destructive_gated — ungated destructive raises")
    _check_raises(
        "fake_delete_capability ungated raises ValueError",
        _assert_destructive_gated, "fake_delete_capability", False, False,
        exc_type=ValueError, must_contain="destructive-name pattern",
    )
    _check_raises(
        "memory_purge ungated raises with verb token list",
        _assert_destructive_gated, "memory_purge", False, False,
        exc_type=ValueError, must_contain="purge",
    )
    _check_raises(
        "document_remove ungated raises with allowlist hint",
        _assert_destructive_gated, "document_remove", False, False,
        exc_type=ValueError, must_contain="_DESTRUCTIVE_GATING_ALLOWLIST",
    )


def test_allowlist_bypasses_assertion():
    """Keys explicitly listed in _DESTRUCTIVE_GATING_ALLOWLIST escape
    the assertion. Verifies the escape-hatch works without needing to
    permanently add a real key to the allowlist."""
    print("\n# allowlist escape hatch")
    # Temporarily extend the allowlist via monkeypatch.
    original = capabilities._DESTRUCTIVE_GATING_ALLOWLIST
    try:
        capabilities._DESTRUCTIVE_GATING_ALLOWLIST = frozenset(
            list(original) + ["fake_archive_legit"]
        )
        _check_no_raise(
            "allowlisted destructive-keyed capability passes",
            capabilities._assert_destructive_gated,
            "fake_archive_legit", False, False,
        )
        # And the non-allowlisted sibling still fails.
        _check_raises(
            "non-allowlisted sibling still raises",
            capabilities._assert_destructive_gated,
            "fake_archive_other", False, False,
            exc_type=ValueError,
        )
    finally:
        capabilities._DESTRUCTIVE_GATING_ALLOWLIST = original


def test_register_capability_calls_assertion():
    """The hook in register_capability must call the assertion before
    touching the DB. Patch get_conn so we can verify the assertion
    fires BEFORE any SQL would run, and that legitimate gated
    registrations are not blocked."""
    print("\n# register_capability — hook fires before SQL")

    # Case 1: ungated destructive registration raises before opening a
    # connection (get_conn never called).
    with unittest.mock.patch.object(capabilities, "get_conn") as mock_conn:
        try:
            capabilities.register_capability(
                capability_key="future_data_delete",
                description="x",
                external_effect=False,
                approval_required=False,
            )
            results.append(("register_capability ungated destructive raises", False))
            print("  FAIL  register_capability ungated destructive raises :: did not raise")
        except ValueError as e:
            _check(
                "register_capability ungated destructive raises (caught ValueError)",
                "destructive-name pattern" in str(e),
                True,
            )
        _check(
            "register_capability did NOT open DB connection on assertion failure",
            mock_conn.call_count,
            0,
        )

    # Case 2: gated destructive registration progresses past the
    # assertion and attempts the DB write (which the mock satisfies).
    with unittest.mock.patch.object(capabilities, "get_conn") as mock_conn:
        mock_cur = unittest.mock.MagicMock()
        mock_cur.fetchone.return_value = (999,)
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
        try:
            capabilities.register_capability(
                capability_key="future_data_delete",
                description="x",
                external_effect=True,
                approval_required=True,
            )
            _check("gated destructive registration proceeds to DB", True, True)
        except ValueError as e:
            results.append(("gated destructive registration proceeds to DB", False))
            print(f"  FAIL  gated destructive registration proceeds to DB :: assertion fired unexpectedly: {e}")

    # Case 3: non-destructive registration always proceeds.
    with unittest.mock.patch.object(capabilities, "get_conn") as mock_conn:
        mock_cur = unittest.mock.MagicMock()
        mock_cur.fetchone.return_value = (999,)
        mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cur
        try:
            capabilities.register_capability(
                capability_key="memory_recall",
                description="x",
                external_effect=False,
                approval_required=False,
            )
            _check("non-destructive registration proceeds", True, True)
        except ValueError as e:
            results.append(("non-destructive registration proceeds", False))
            print(f"  FAIL  non-destructive registration proceeds :: {e}")


def test_update_capability_re_checks_when_flags_change():
    """update_capability must re-run the assertion when either gate
    flag is being modified. Setting external_effect=False on a
    destructive-keyed row with approval_required also False should
    raise; setting them both to False on a non-destructive row is fine."""
    print("\n# update_capability — re-checks gate flags")

    # Patch get_capability so we control the existing row state.
    with unittest.mock.patch.object(
        capabilities, "get_capability",
        return_value={
            "capability_key": "vinted_draft_archive",
            "external_effect": False,
            "approval_required": True,
        },
    ):
        try:
            capabilities.update_capability(
                "vinted_draft_archive",
                approval_required=False,  # flipping False — would un-gate
            )
            results.append(("update_capability un-gating destructive raises", False))
            print("  FAIL  update_capability un-gating destructive raises :: did not raise")
        except ValueError as e:
            _check(
                "update_capability un-gating destructive raises (caught ValueError)",
                "destructive-name pattern" in str(e),
                True,
            )

    # Non-destructive key update should not trigger the assertion at
    # all. The DB path is short-circuited at the assertion check —
    # we're verifying the validation gate doesn't raise on
    # non-destructive keys, not that the SQL completes. Patch the
    # whole connection chain so rowcount returns a real int.
    with unittest.mock.patch.object(capabilities, "get_conn") as mock_conn:
        cur_obj = unittest.mock.MagicMock()
        cur_obj.rowcount = 1
        # Build the context-manager chain: get_conn() → conn,
        # `with conn:` → conn, `with conn.cursor() as cur` → cur_obj
        conn_obj = mock_conn.return_value
        conn_obj.__enter__.return_value = conn_obj
        conn_obj.cursor.return_value.__enter__.return_value = cur_obj
        try:
            capabilities.update_capability(
                "memory_recall",
                approval_required=False,
            )
            _check("non-destructive key update proceeds", True, True)
        except ValueError as e:
            results.append(("non-destructive key update proceeds", False))
            print(f"  FAIL  non-destructive key update proceeds :: {e}")


# ── Runner ──────────────────────────────────────────────────────────────


def main():
    test_is_destructive_key_positive()
    test_is_destructive_key_negative()
    test_is_destructive_key_edge_cases()
    test_assert_passes_for_gated_destructive()
    test_assert_passes_for_non_destructive()
    test_assert_fails_for_ungated_destructive()
    test_allowlist_bypasses_assertion()
    test_register_capability_calls_assertion()
    test_update_capability_re_checks_when_flags_change()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    failed = total - passed
    print()
    print("=" * 60)
    print(f"destructive-gate assertion tests: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
