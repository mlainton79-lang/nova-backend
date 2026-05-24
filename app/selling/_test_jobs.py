#!/usr/bin/env python3
"""Tests for app.selling.jobs CRUD. Invokable directly (no pytest dep).

Usage (from repo root):
    DATABASE_URL=<url> /usr/bin/python3 app/selling/_test_jobs.py

Each test inserts a row with account prefix "test_selling_" and either
platform='other' or platform='ebay' (to also exercise the platform CHECK
constraint with a real entry), then deletes it. Final check: starting/ending
count on tony_selling_jobs must match (no leaked rows).

Exit 0 if all tests pass, 1 otherwise.

Scope: jobs.py CRUD only. Operator stub tests (async) deferred to session 2+
when the real eBay operator lands and there's something real to test.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.selling import jobs  # noqa: E402

import psycopg2  # noqa: E402

TEST_ACCOUNT_PREFIX = "test_selling_"
results = []


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def count_jobs():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM tony_selling_jobs")
            return cur.fetchone()[0]
    finally:
        conn.close()


def cleanup_test_rows():
    """Delete any rows left over from test runs."""
    conn = get_conn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tony_selling_jobs WHERE account LIKE %s",
                (TEST_ACCOUNT_PREFIX + "%",),
            )
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


# ─── 9 test cases ───────────────────────────────────────────────────


def test_1_create_job_returns_int():
    jid = jobs.create_job(
        platform="other",
        item_name="case 1: basic create_job",
        account=TEST_ACCOUNT_PREFIX + "c1",
    )
    assert jid is not None, "expected int id, got None"
    assert isinstance(jid, int), f"expected int, got {type(jid).__name__}"


def test_2_get_job_returns_dict():
    jid = jobs.create_job(
        platform="ebay",
        item_name="case 2: get_job after create",
        account=TEST_ACCOUNT_PREFIX + "c2",
        metadata={"k": "v", "n": 42},
    )
    assert jid is not None
    row = jobs.get_job(jid)
    assert row is not None, "row not found after insert"
    assert row["id"] == jid
    assert row["platform"] == "ebay"
    assert row["status"] == "queued", f"default status should be 'queued', got {row['status']!r}"
    assert row["account"].startswith(TEST_ACCOUNT_PREFIX)
    assert row["metadata_json"] == {"k": "v", "n": 42}, f"metadata mismatch: {row['metadata_json']!r}"


def test_3_invalid_platform_returns_none():
    jid = jobs.create_job(
        platform="bogus_platform",
        item_name="case 3: invalid platform should be rejected",
        account=TEST_ACCOUNT_PREFIX + "c3",
    )
    assert jid is None, f"expected None for invalid platform, got {jid!r}"


def test_4_get_job_nonexistent_returns_none():
    row = jobs.get_job(999999999)
    assert row is None, f"expected None for non-existent job, got {row!r}"


def test_5_update_status_transitions():
    jid = jobs.create_job(
        platform="other",
        item_name="case 5: status transitions",
        account=TEST_ACCOUNT_PREFIX + "c5",
    )
    assert jid is not None

    ok = jobs.update_status(jid, "starting")
    assert ok is True
    row = jobs.get_job(jid)
    assert row["status"] == "starting"
    assert row["started_at"] is not None, "started_at should be auto-stamped on transition to 'starting'"

    ok = jobs.update_status(jid, "submitting")
    assert ok is True

    ok = jobs.update_status(
        jid, "posted_confirmed",
        platform_listing_id="EBAY-123456",
        platform_listing_url="https://ebay.co.uk/itm/123456",
    )
    assert ok is True
    row = jobs.get_job(jid)
    assert row["status"] == "posted_confirmed"
    assert row["platform_listing_id"] == "EBAY-123456"
    assert row["platform_listing_url"] == "https://ebay.co.uk/itm/123456"
    assert row["completed_at"] is not None
    assert row["posted_confirmed_at"] is not None


def test_6_update_status_invalid_returns_false():
    jid = jobs.create_job(
        platform="other",
        item_name="case 6: invalid status rejected",
        account=TEST_ACCOUNT_PREFIX + "c6",
    )
    assert jid is not None
    ok = jobs.update_status(jid, "bogus_status")
    assert ok is False, "expected False for invalid status"
    # Job's status should still be 'queued'
    row = jobs.get_job(jid)
    assert row["status"] == "queued"


def test_7_update_status_failed_sets_error_fields():
    jid = jobs.create_job(
        platform="ebay",
        item_name="case 7: failed transition with error fields",
        account=TEST_ACCOUNT_PREFIX + "c7",
    )
    assert jid is not None
    ok = jobs.update_status(
        jid, "failed",
        error_message="simulated test failure",
        error_type="test_simulated",
    )
    assert ok is True
    row = jobs.get_job(jid)
    assert row["status"] == "failed"
    assert row["error_message"] == "simulated test failure"
    assert row["error_type"] == "test_simulated"
    assert row["completed_at"] is not None


def test_8_append_event_creates_event_row():
    jid = jobs.create_job(
        platform="other",
        item_name="case 8: append_event",
        account=TEST_ACCOUNT_PREFIX + "c8",
    )
    assert jid is not None
    eid = jobs.append_event(
        jid, "capability_unavailable",
        message="stub event for test",
        metadata={"stage": "test"},
    )
    assert eid is not None
    assert isinstance(eid, int)
    # Verify the event row exists by direct SQL
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, message, metadata_json FROM tony_selling_job_events WHERE id = %s",
                (eid,),
            )
            ev = cur.fetchone()
            assert ev is not None
            assert ev[0] == "capability_unavailable"
            assert ev[1] == "stub event for test"
            assert ev[2] == {"stage": "test"}
    finally:
        conn.close()


def test_9_list_jobs_filters():
    # Create 2 ebay + 1 other under distinct test account names
    j1 = jobs.create_job(platform="ebay", item_name="case 9a", account=TEST_ACCOUNT_PREFIX + "c9a")
    j2 = jobs.create_job(platform="ebay", item_name="case 9b", account=TEST_ACCOUNT_PREFIX + "c9b")
    j3 = jobs.create_job(platform="other", item_name="case 9c", account=TEST_ACCOUNT_PREFIX + "c9c")
    assert j1 and j2 and j3
    # No filter — should return our 3 (probably more from earlier in the run)
    all_rows = jobs.list_jobs(limit=50)
    assert isinstance(all_rows, list)
    assert len(all_rows) >= 3
    # platform='ebay' filter — should include j1 and j2 but not j3
    ebay_rows = jobs.list_jobs(platform="ebay", limit=50)
    ebay_ids = {r["id"] for r in ebay_rows}
    assert j1 in ebay_ids and j2 in ebay_ids and j3 not in ebay_ids


TESTS = [
    ("1. create_job returns int", test_1_create_job_returns_int),
    ("2. get_job returns dict with all fields", test_2_get_job_returns_dict),
    ("3. invalid platform returns None", test_3_invalid_platform_returns_none),
    ("4. get_job non-existent returns None", test_4_get_job_nonexistent_returns_none),
    ("5. update_status lifecycle transitions + auto-stamping", test_5_update_status_transitions),
    ("6. update_status invalid status returns False", test_6_update_status_invalid_returns_false),
    ("7. update_status failed sets error fields + completed_at", test_7_update_status_failed_sets_error_fields),
    ("8. append_event creates event row with metadata", test_8_append_event_creates_event_row),
    ("9. list_jobs respects platform filter", test_9_list_jobs_filters),
]


def main():
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set. Invoke like:")
        print("  DATABASE_URL=<url> /usr/bin/python3 app/selling/_test_jobs.py")
        return 2

    start_count = count_jobs()
    print(f"tony_selling_jobs starting count: {start_count}")
    print()
    print("Running 9 test cases:")

    for name, fn in TESTS:
        run_test(name, fn)

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"PASSED: {passed}/{len(results)}    FAILED: {failed}")

    # Cleanup test rows + verify count parity
    leaked = cleanup_test_rows()
    print(f"emergency cleanup: deleted {leaked} test rows")
    end_count = count_jobs()
    print(f"tony_selling_jobs ending count: {end_count} (was {start_count})")
    if end_count != start_count:
        print(f"WARN: count delta = {end_count - start_count}")

    return 0 if failed == 0 and end_count == start_count else 1


if __name__ == "__main__":
    sys.exit(main())
