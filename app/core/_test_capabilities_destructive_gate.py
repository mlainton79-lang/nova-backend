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

# Stub heavy deps so we can import capabilities.py + capability_builder.py
# without a DB or live httpx. Both modules use these at import time.
sys.modules.setdefault("psycopg2", unittest.mock.MagicMock())
sys.modules.setdefault("psycopg2.extras", unittest.mock.MagicMock())
sys.modules.setdefault("httpx", unittest.mock.MagicMock())
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


def test_backfill_loop_skips_ungated_destructive_legacy():
    """The init_capabilities_table backfill loop must NOT silently
    copy a legacy *_delete / *_archive row into canonical if it
    isn't gated. Codex round-3 review flagged this as a bypass:
    capability_builder used to write to legacy directly, and a
    builder-created destructive row would have ridden the backfill
    into canonical without the assertion firing.

    The loop now calls _assert_destructive_gated for every legacy
    row and skips (logs) the ones that fail."""
    print("\n# init backfill skips ungated destructive legacy rows")

    # We can't easily integration-test init_capabilities_table without
    # a DB, but we can exercise the per-row gate by simulating what
    # the loop does. Build the same input as a legacy row and confirm
    # the assertion-raising behaviour matches what the loop relies on.
    _check_raises(
        "legacy ungated destructive row fails the per-row check",
        capabilities._assert_destructive_gated,
        "legacy_fake_delete", False, False,
        exc_type=ValueError, must_contain="destructive-name pattern",
    )
    _check_no_raise(
        "legacy gated destructive row (approval_required=True) passes",
        capabilities._assert_destructive_gated,
        "legacy_fake_delete", False, True,
    )
    _check_no_raise(
        "legacy non-destructive row passes regardless of flags",
        capabilities._assert_destructive_gated,
        "legacy_memory_recall", False, False,
    )


def test_capability_builder_routes_through_canonical():
    """capability_builder.register_capability previously wrote
    directly to the legacy `capabilities` table — bypassing the
    assertion. It now routes through app.core.capabilities.upsert_
    capability so the same gate fires.

    Patch upsert_capability and confirm it gets called instead of
    a raw SQL write to the legacy table."""
    print("\n# capability_builder routes through canonical facade")
    from app.core import capability_builder

    # Mock get_capability=None so the builder's R2.1 split-path takes
    # the new-key → upsert_capability branch (the path this test
    # asserts). Without this, get_capability would hit the real
    # get_conn() which fails on the missing DATABASE_URL env var, the
    # builder's outer except would swallow the KeyError, and
    # mock_upsert would never be called.
    with unittest.mock.patch.object(capabilities, "get_capability", return_value=None), \
         unittest.mock.patch("app.core.capabilities.upsert_capability") as mock_upsert:
        mock_upsert.return_value = 12345
        capability_builder.register_capability(
            name="some_new_skill",
            description="x",
            endpoint="/api/v1/some_new_skill",
        )
        _check(
            "upsert_capability called once",
            mock_upsert.call_count,
            1,
        )
        # Confirm the call shape — keyword args match what the facade
        # expects, and status='active' is passed.
        kwargs = mock_upsert.call_args.kwargs
        _check("name argument", kwargs.get("name"), "some_new_skill")
        _check("status defaulted to active", kwargs.get("status"), "active")

    # Now confirm that an ungated destructive name routes through and
    # the ValueError is caught (non-fatal — printed not raised). Same
    # get_capability=None mock so the builder reaches the upsert path.
    with unittest.mock.patch.object(capabilities, "get_capability", return_value=None), \
         unittest.mock.patch("app.core.capabilities.upsert_capability") as mock_upsert:
        mock_upsert.side_effect = ValueError("destructive-name pattern...")
        # Should NOT raise — the builder catches ValueError and prints.
        try:
            capability_builder.register_capability(
                name="some_data_delete",
                description="hostile",
                endpoint="/api/v1/some_data_delete",
            )
            _check("builder catches assertion ValueError non-fatally", True, True)
        except ValueError:
            results.append(("builder catches assertion ValueError non-fatally", False))
            print("  FAIL  builder catches assertion ValueError non-fatally :: re-raised")


def test_audit_destructive_gating_dual_table():
    """audit_destructive_gating() must scan BOTH tony_capabilities
    (canonical) AND legacy `capabilities` so skipped legacy rows
    surface to operators. Codex round-4 nit closure."""
    print("\n# audit_destructive_gating — dual-table scan")

    # Build a mock cursor that returns different rowsets per query.
    # The audit issues three queries: (1) canonical scan, (2) legacy
    # existence check, (3) legacy scan.
    queries_seen = []

    class MockCursor:
        def __init__(self):
            self.rowsets = [
                # (1) canonical scan → one ungated destructive row
                [("canonical_test_purge", "medium", False, False, "active")],
                # (2) legacy-existence → True
                [(True,)],
                # (3) legacy scan → one ungated destructive row
                [("legacy_test_remove", "low", False, "active")],
            ]
            self._call = 0

        def execute(self, sql, params=None):
            queries_seen.append(sql.strip()[:60])

        def fetchall(self):
            rs = self.rowsets[min(self._call, len(self.rowsets) - 1)]
            self._call += 1
            # Each "scan" call uses fetchall; the existence-check uses
            # fetchone — let's increment after the canonical scan and
            # the legacy scan.
            return rs

        def fetchone(self):
            # existence check returns a tuple
            rs = self.rowsets[min(self._call, len(self.rowsets) - 1)]
            self._call += 1
            return rs[0] if rs else None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockConn:
        def cursor(self):
            return MockCursor()
        def close(self):
            pass

    with unittest.mock.patch.object(capabilities, "get_conn", return_value=MockConn()):
        violations = capabilities.audit_destructive_gating()

    _check("audit returns 2 violations (one canonical, one legacy)", len(violations), 2)
    sources = {v.get("source_table") for v in violations}
    _check("audit includes tony_capabilities source", "tony_capabilities" in sources, True)
    _check("audit includes legacy capabilities source", "capabilities" in sources, True)
    # Verify legacy row has external_effect=False asserted (column
    # doesn't exist; audit assumes False to match the backfill loop).
    legacy_v = next((v for v in violations if v.get("source_table") == "capabilities"), None)
    _check("legacy violation key", legacy_v and legacy_v.get("capability_key"), "legacy_test_remove")
    _check("legacy violation external_effect assumed False", legacy_v and legacy_v.get("external_effect"), False)


def test_update_capability_re_checks_when_flags_change():
    """update_capability must re-run the assertion on every update of
    a destructive-keyed row (including updates that don't touch the
    gate flags — see
    test_update_capability_re_asserts_with_no_gate_field_in_update
    below). This test covers the flag-flip slice: setting
    approval_required=False on a destructive-keyed row whose only
    gate was approval_required must raise; the same flag on a
    non-destructive row is fine."""
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


def test_update_capability_re_asserts_with_no_gate_field_in_update():
    """THE hardening test (closes
    nova-docs/2026-06-06-capbuilder-activation-gate-gap.md).

    Pre-hardening, the outer if-guard
        if "external_effect" in canonical or "approval_required" in canonical:
    meant an update that only set status / capability_type / source on
    an existing destructive-keyed row with both gate flags False would
    silently activate the row — _assert_destructive_gated was never
    invoked. The hardening drops that guard; the assertion now runs on
    every update of a destructive-keyed row, using the merged
    post-update state (fields not in the payload default to the
    existing-row value).

    This test simulates the dangerous precondition (ungated
    destructive row pre-existing in the registry — unreachable today
    via any INSERT path, but defence-in-depth) and asserts the update
    now raises ValueError instead of silently activating."""
    print("\n# update_capability — re-asserts even with no gate field in update")

    # Existing destructive-keyed row that is somehow already ungated.
    with unittest.mock.patch.object(
        capabilities, "get_capability",
        return_value={
            "capability_key": "vinted_draft_archive",
            "external_effect": False,
            "approval_required": False,
        },
    ):
        try:
            capabilities.update_capability(
                "vinted_draft_archive",
                status="active",
                capability_type="http_endpoint",
                # NOTE: no external_effect, no approval_required in the
                # payload. Pre-hardening, the outer if-guard would have
                # skipped the assertion entirely on this call shape.
            )
            results.append(
                ("update_capability ungated-existing-row + no-gate-field raises", False)
            )
            print(
                "  FAIL  update_capability ungated-existing-row + no-gate-field raises"
                " :: did not raise"
            )
        except ValueError as e:
            _check(
                "update_capability ungated-existing-row + no-gate-field raises (caught ValueError)",
                "destructive-name pattern" in str(e),
                True,
            )


def test_update_capability_no_false_deny_on_gated_existing_row():
    """Hardening must not false-deny: an innocuous status/type-only
    update of a CORRECTLY GATED destructive-keyed row must still
    succeed. The merged-state assertion sees at least one gate flag
    True (from the existing row's defaults when the payload omits
    them) and passes."""
    print("\n# update_capability — no false-deny on gated row")

    # Existing destructive-keyed row is correctly gated
    # (approval_required=True). An update with no gate flag in the
    # payload must NOT raise — new_approval defaults to existing True.
    with unittest.mock.patch.object(
        capabilities, "get_capability",
        return_value={
            "capability_key": "vinted_draft_archive",
            "external_effect": False,
            "approval_required": True,
        },
    ):
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
                    "vinted_draft_archive",
                    status="active",
                    capability_type="http_endpoint",
                )
                _check(
                    "gated destructive row, status/type-only update, no false-deny",
                    True, True,
                )
            except ValueError as e:
                results.append(
                    ("gated destructive row, status/type-only update, no false-deny", False)
                )
                print(
                    f"  FAIL  gated destructive row, status/type-only update,"
                    f" no false-deny :: {e}"
                )


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
    test_backfill_loop_skips_ungated_destructive_legacy()
    test_capability_builder_routes_through_canonical()
    test_audit_destructive_gating_dual_table()
    test_update_capability_re_checks_when_flags_change()
    test_update_capability_re_asserts_with_no_gate_field_in_update()
    test_update_capability_no_false_deny_on_gated_existing_row()

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
