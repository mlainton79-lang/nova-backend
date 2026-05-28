#!/usr/bin/env python3
"""Tests for app.selling.drafts CRUD + image-staging helpers. Invokable
directly (no pytest dep).

Usage (from repo root):
    DATABASE_URL=<url> /usr/bin/python3 app/selling/_test_drafts.py

Each test inserts rows with source='test_selling_drafts' so they can be
fully isolated and cleaned. Final check: starting/ending count on
tony_drafts must match (no leaked rows).

Image-staging tests use a temp NOVA_DRAFT_STORAGE_BASE override so they
don't write to /data/ on the real volume.

Exit 0 if all tests pass, 1 otherwise.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Tests want a writable storage base — override before importing the module.
_TEST_STORAGE_BASE = tempfile.mkdtemp(prefix="nova_drafts_test_")
os.environ.setdefault("NOVA_DRAFT_STORAGE_BASE", _TEST_STORAGE_BASE)

from app.selling import drafts  # noqa: E402

import psycopg2  # noqa: E402

TEST_SOURCE = "test_selling_drafts"
results = []


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def count_drafts():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM tony_drafts")
            return cur.fetchone()[0]
    finally:
        conn.close()


def cleanup_test_rows():
    conn = get_conn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tony_drafts WHERE source = %s",
                (TEST_SOURCE,),
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


# ─── tests ───────────────────────────────────────────────────────────


def test_1_create_draft_returns_int():
    did = drafts.create_draft(
        source=TEST_SOURCE,
        canonical_title="Test item",
        canonical_description="A test draft.",
        item_facts={"brand": "TestBrand", "category": "other"},
        pricing={"suggested_uk_resale_price": 12.50},
        warnings=["test_warning"],
    )
    assert isinstance(did, int) and did > 0, f"expected int id, got {did!r}"


def test_2_get_draft_returns_dict_with_defaults():
    did = drafts.create_draft(source=TEST_SOURCE, canonical_title="x")
    row = drafts.get_draft(did)
    assert isinstance(row, dict), f"expected dict, got {type(row)}"
    assert row["id"] == did
    assert row["status"] == "draft_generated", f"unexpected status {row['status']!r}"
    assert row["approval_state"] == "pending_review", f"unexpected approval_state {row['approval_state']!r}"
    assert row["canonical_title"] == "x"
    assert row["images_json"] == [], f"expected empty images_json, got {row['images_json']!r}"


def test_3_get_draft_missing_returns_none():
    row = drafts.get_draft(999999999)
    assert row is None, f"expected None for missing draft, got {row!r}"


def test_4_update_images_json_replaces_list():
    did = drafts.create_draft(source=TEST_SOURCE)
    handles = [{
        "id": "img-1",
        "storage": "railway_volume",
        "path": f"drafts/{did}/photos/img-1.jpg",
        "mime": "image/jpeg",
        "sha256": "deadbeef",
        "size_bytes": 100,
        "role": "primary",
        "ordinal": 0,
    }]
    ok = drafts.update_images_json(did, handles)
    assert ok is True, "update_images_json should return True"
    row = drafts.get_draft(did)
    assert row["images_json"] == handles, f"images_json round-trip mismatch: {row['images_json']!r}"


def test_5_update_draft_fields_partial():
    did = drafts.create_draft(source=TEST_SOURCE, canonical_title="initial")
    ok = drafts.update_draft_fields(
        did,
        canonical_description="updated",
        status="needs_review",
    )
    assert ok is True
    row = drafts.get_draft(did)
    assert row["canonical_title"] == "initial", "title should be untouched"
    assert row["canonical_description"] == "updated"
    assert row["status"] == "needs_review"


def test_6_resolve_image_path_valid():
    """A handle pointing inside drafts/ resolves to an absolute path."""
    entry = {
        "storage": "railway_volume",
        "path": "drafts/42/photos/abc.jpg",
    }
    resolved = drafts.resolve_image_path(entry)
    assert resolved is not None, "valid handle should resolve"
    assert resolved.endswith("/drafts/42/photos/abc.jpg"), f"unexpected resolved path: {resolved!r}"


def test_7_resolve_image_path_rejects_escape():
    """A handle with '..' segments that escape /drafts/ must be rejected."""
    entry = {
        "storage": "railway_volume",
        "path": "drafts/42/photos/../../../etc/passwd",
    }
    resolved = drafts.resolve_image_path(entry)
    assert resolved is None, f"path-escape attempt must return None, got {resolved!r}"


def test_8_resolve_image_path_rejects_unsupported_storage():
    """Storage type other than railway_volume is rejected."""
    entry = {"storage": "s3", "path": "drafts/42/photos/abc.jpg"}
    resolved = drafts.resolve_image_path(entry)
    assert resolved is None, "non-railway_volume storage must return None"


def test_9_resolve_image_path_rejects_sibling_directory():
    """drafts/-adjacent paths like draftsX/ must not satisfy the prefix guard."""
    entry = {
        "storage": "railway_volume",
        "path": "draftsX/42/photos/abc.jpg",
    }
    resolved = drafts.resolve_image_path(entry)
    assert resolved is None, "sibling-dir path must be rejected by os.sep guard"


def test_10_stage_image_bytes_writes_and_round_trips():
    did = drafts.create_draft(source=TEST_SOURCE)
    image_bytes = b"\xff\xd8\xff\xe0test-jpeg-bytes" + b"\x00" * 32
    rel_path = drafts.stage_image_bytes(did, "img-test", image_bytes, "jpg")
    assert rel_path is not None and rel_path.endswith(f"drafts/{did}/photos/img-test.jpg"), \
        f"unexpected rel_path: {rel_path!r}"

    # Round-trip through resolve_image_path → confirm the bytes are there.
    resolved = drafts.resolve_image_path({"storage": "railway_volume", "path": rel_path})
    assert resolved is not None, "staged file should resolve"
    assert os.path.exists(resolved), f"staged file should exist on disk at {resolved!r}"
    with open(resolved, "rb") as f:
        on_disk = f.read()
    assert on_disk == image_bytes, "staged bytes round-trip mismatch"

    # Cleanup
    drafts.delete_staged_images(did)
    assert not os.path.exists(resolved), "delete_staged_images should remove the file"


def test_11_delete_draft_removes_row():
    did = drafts.create_draft(source=TEST_SOURCE)
    assert drafts.get_draft(did) is not None
    assert drafts.delete_draft(did) is True
    assert drafts.get_draft(did) is None


def test_12_interlock_check_enforced_by_db():
    """The DB CHECK constraint rejects status='approved' while
    approval_state='pending_review'. Direct SQL because the module's
    update_draft_fields can be called with status='approved' — the DB
    is the backstop."""
    did = drafts.create_draft(source=TEST_SOURCE)
    raised = False
    try:
        conn = get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tony_drafts SET status='approved' WHERE id=%s",
                (did,),
            )
        conn.close()
    except psycopg2.errors.CheckViolation:
        raised = True
    except Exception as e:
        raise AssertionError(f"expected CheckViolation, got {type(e).__name__}: {e}")
    assert raised, "DB CHECK constraint should reject status=approved when approval_state=pending_review"


# ─── runner ──────────────────────────────────────────────────────────


if __name__ == "__main__":
    if "DATABASE_URL" not in os.environ:
        print("FATAL: DATABASE_URL not set")
        sys.exit(1)

    drafts.init_drafts_table()
    start_count = count_drafts()
    cleanup_test_rows()

    tests = [
        ("create_draft returns int",                              test_1_create_draft_returns_int),
        ("get_draft returns dict with defaults",                  test_2_get_draft_returns_dict_with_defaults),
        ("get_draft missing returns None",                        test_3_get_draft_missing_returns_none),
        ("update_images_json replaces list",                      test_4_update_images_json_replaces_list),
        ("update_draft_fields partial update",                    test_5_update_draft_fields_partial),
        ("resolve_image_path valid handle",                       test_6_resolve_image_path_valid),
        ("resolve_image_path rejects escape",                     test_7_resolve_image_path_rejects_escape),
        ("resolve_image_path rejects unsupported storage",        test_8_resolve_image_path_rejects_unsupported_storage),
        ("resolve_image_path rejects sibling dir",                test_9_resolve_image_path_rejects_sibling_directory),
        ("stage_image_bytes writes + round-trips",                test_10_stage_image_bytes_writes_and_round_trips),
        ("delete_draft removes row",                              test_11_delete_draft_removes_row),
        ("interlock CHECK rejects status=approved on pending",    test_12_interlock_check_enforced_by_db),
    ]
    for name, fn in tests:
        run_test(name, fn)

    cleaned = cleanup_test_rows()
    end_count = count_drafts()
    print(f"\nstart_count={start_count} end_count={end_count} cleaned={cleaned}")
    assert end_count == start_count, "leaked rows!"

    fails = [r for r in results if not r[1]]
    if fails:
        print(f"\n{len(fails)} FAILED")
        sys.exit(1)
    print(f"\nall {len(results)} tests PASS")
