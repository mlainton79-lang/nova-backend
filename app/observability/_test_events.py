#!/usr/bin/env python3
"""Tests for record_run_event. Invokable directly (no pytest dep).

Usage (from repo root):
    DATABASE_URL=<url> /usr/bin/python3 app/observability/_test_events.py

Each test inserts a row with event_type prefix "test_observability_",
verifies it, then deletes it. Final check: starting/ending run_events
count must match (no leaked rows).

Exit 0 if all 8 cases pass, 1 otherwise.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.observability import record_run_event, EventSeverity  # noqa: E402

import psycopg2  # noqa: E402

TEST_EVENT_TYPE_PREFIX = "test_observability_"
results = []


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def fetch_row(event_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, event_type, severity, subsystem, message, metadata_json "
                "FROM run_events WHERE id = %s",
                (event_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def delete_row(event_id):
    conn = get_conn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM run_events WHERE id = %s", (event_id,))
            return cur.rowcount
    finally:
        conn.close()


def run_test(name, fn):
    try:
        fn()
        results.append((name, True, ""))
        print(f"  PASS  {name}")
    except AssertionError as e:
        results.append((name, False, str(e)))
        print(f"  FAIL  {name}: {e}")
    except Exception as e:
        results.append((name, False, f"unexpected {type(e).__name__}: {e}"))
        print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")


# ─── 8 test cases ────────────────────────────────────────────────


def test_1_enum_severity():
    eid = record_run_event(
        event_type=TEST_EVENT_TYPE_PREFIX + "case1",
        severity=EventSeverity.INFO,
        subsystem="test.unit",
        message="case 1: EventSeverity.INFO + valid inputs",
    )
    assert eid is not None, "expected int id, got None"
    assert isinstance(eid, int), f"expected int, got {type(eid).__name__}"
    row = fetch_row(eid)
    assert row is not None, "row not found after insert"
    assert row[2] == "info", f"severity should be 'info', got {row[2]!r}"
    delete_row(eid)


def test_2_string_severity():
    eid = record_run_event(
        event_type=TEST_EVENT_TYPE_PREFIX + "case2",
        severity="info",
        subsystem="test.unit",
        message="case 2: severity='info' (string)",
    )
    assert eid is not None
    row = fetch_row(eid)
    assert row is not None
    assert row[2] == "info"
    delete_row(eid)


def test_3_invalid_severity_coerces():
    eid = record_run_event(
        event_type=TEST_EVENT_TYPE_PREFIX + "case3",
        severity="bogus",
        subsystem="test.unit",
        message="case 3: severity='bogus' coerces to 'error'",
    )
    assert eid is not None, "expected insert to succeed with coerced severity"
    row = fetch_row(eid)
    assert row is not None
    assert row[2] == "error", f"bogus should have coerced to 'error', got {row[2]!r}"
    delete_row(eid)


def test_4_metadata_dict():
    eid = record_run_event(
        event_type=TEST_EVENT_TYPE_PREFIX + "case4",
        severity="info",
        subsystem="test.unit",
        message="case 4: metadata is dict",
        metadata={"k": "v", "n": 42},
    )
    assert eid is not None
    row = fetch_row(eid)
    assert row is not None
    md = row[5]
    assert isinstance(md, dict), f"JSONB should decode to dict, got {type(md).__name__}"
    assert md.get("k") == "v" and md.get("n") == 42, f"metadata mismatch: {md!r}"
    delete_row(eid)


def test_5_non_serializable_metadata():
    bad = {}
    bad["self"] = bad
    eid = record_run_event(
        event_type=TEST_EVENT_TYPE_PREFIX + "case5",
        severity="info",
        subsystem="test.unit",
        message="case 5: non-JSON-serializable metadata, stores '{}'",
        metadata=bad,
    )
    assert eid is not None, "expected insert to succeed with metadata fallback"
    row = fetch_row(eid)
    assert row is not None
    md = row[5]
    assert md == {}, f"expected empty {{}}, got {md!r}"
    delete_row(eid)


def test_6_no_database_url():
    saved = os.environ.pop("DATABASE_URL", None)
    try:
        eid = record_run_event(
            event_type=TEST_EVENT_TYPE_PREFIX + "case6",
            severity="info",
            subsystem="test.unit",
            message="case 6: DATABASE_URL unset, should return None",
        )
        assert eid is None, f"expected None when DATABASE_URL unset, got {eid!r}"
    finally:
        if saved is not None:
            os.environ["DATABASE_URL"] = saved


def test_7_unreachable_db():
    saved = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "postgresql://x:y@127.0.0.1:1/none"
    try:
        eid = record_run_event(
            event_type=TEST_EVENT_TYPE_PREFIX + "case7",
            severity="info",
            subsystem="test.unit",
            message="case 7: unreachable DB, should return None",
        )
        assert eid is None, f"expected None for unreachable DB, got {eid!r}"
    finally:
        if saved is not None:
            os.environ["DATABASE_URL"] = saved
        else:
            os.environ.pop("DATABASE_URL", None)


def test_8_all_defaults():
    eid = record_run_event(
        event_type=TEST_EVENT_TYPE_PREFIX + "case8",
        severity="info",
        subsystem="test.unit",
        message="case 8: only 4 required kwargs, all optional defaults applied",
    )
    assert eid is not None
    row = fetch_row(eid)
    assert row is not None
    delete_row(eid)


TESTS = [
    ("1. EventSeverity.INFO + valid inputs", test_1_enum_severity),
    ("2. severity='info' (string)", test_2_string_severity),
    ("3. severity='bogus' coerces to 'error'", test_3_invalid_severity_coerces),
    ("4. metadata={k:v, n:42}", test_4_metadata_dict),
    ("5. non-JSON-serializable metadata fallback", test_5_non_serializable_metadata),
    ("6. DATABASE_URL unset returns None", test_6_no_database_url),
    ("7. unreachable DB returns None", test_7_unreachable_db),
    ("8. all None optional kwargs", test_8_all_defaults),
]


def main():
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set. Invoke like:")
        print("  DATABASE_URL=<url> /usr/bin/python3 app/observability/_test_events.py")
        return 2

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM run_events")
            start_count = cur.fetchone()[0]
    finally:
        conn.close()
    print(f"run_events starting count: {start_count}")
    print()
    print("Running 8 test cases:")

    for name, fn in TESTS:
        run_test(name, fn)

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"PASSED: {passed}/{len(results)}    FAILED: {failed}")

    conn = get_conn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM run_events WHERE event_type LIKE %s",
                (TEST_EVENT_TYPE_PREFIX + "%",),
            )
            leaked = cur.fetchone()[0]
            if leaked > 0:
                cur.execute(
                    "DELETE FROM run_events WHERE event_type LIKE %s",
                    (TEST_EVENT_TYPE_PREFIX + "%",),
                )
                print(f"emergency cleanup: deleted {cur.rowcount} leaked test rows")
            cur.execute("SELECT COUNT(*) FROM run_events")
            end_count = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"run_events ending count: {end_count} (was {start_count})")
    if end_count != start_count:
        print(f"WARN: count delta = {end_count - start_count}")

    return 0 if failed == 0 and end_count == start_count else 1


if __name__ == "__main__":
    sys.exit(main())
