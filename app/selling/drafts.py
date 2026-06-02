"""tony_drafts — marketplace-agnostic draft persistence + image staging.

Design contract:
  nova-docs/ops/evidence/2026-05-28/SESSION_BRIEF_draft_pipeline_design.md

One row in tony_drafts per photo session. The draft is the canonical, user-
editable listing intent — independent of marketplace. Marketplace-specific
text is rendered lazily into renderings_json when jobs are created (next
session).

Image staging contract:
- Bytes are written atomically to /data/drafts/{draft_id}/photos/{image_id}.{ext}
  (temp file → fsync → os.replace).
- images_json holds STABLE HANDLES with relative paths. Workers resolve
  against the configured NOVA_DRAFT_STORAGE_BASE (default '/data').
- resolve_image_path() is the ONLY way an operator should turn a handle
  back into a filesystem path. It enforces a path-escape guard so a
  malicious or corrupted images_json entry can't read outside /data/drafts/.

Module discipline (per AGENTS.md):
- Per-call psycopg2.connect(sslmode='require', connect_timeout=10). No
  pooling, no ORM.
- Every public function catches Exception, calls record_run_event(
  subsystem='selling.drafts', ...), and returns None / False / [].
  Never raises.
- Leaf import: this module imports only from app.observability + stdlib +
  psycopg2. No app.api imports anywhere.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras

from app.observability import EVENT_TYPES, EventSeverity, record_run_event


# ── Storage base ─────────────────────────────────────────────────────────────
# Configurable via Railway Variable so the same code runs in any environment
# that mounts a volume at a different path. Default '/data' matches the existing
# tony_vinted_jobs photo convention.
_STORAGE_BASE = os.environ.get("NOVA_DRAFT_STORAGE_BASE", "/data")
_DRAFTS_SUBDIR = "drafts"

# Allow-list for stage_image_bytes input validation. The endpoint currently
# passes a UUID + an extension derived from MIME sniff, but stage_image_bytes
# is a public helper — future callers must not be trusted to pre-validate.
_VALID_EXTS = frozenset({"jpg", "jpeg", "png", "webp"})

# Strict basename pattern: alphanumeric + hyphen + underscore only. No path
# separators, no '..', no leading dot. UUIDs (str(uuid.uuid4())) match this.
_SAFE_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _write_all(fd: int, data: bytes) -> None:
    """Write the entire buffer to fd, looping over short writes.

    `os.write()` is allowed to perform a partial write without raising. A
    single unchecked call could land a truncated file while the caller's DB
    record still describes the full payload — silent corruption. This helper
    retries until everything is written or a real OSError is raised.
    """
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(f"os.write returned {written}; expected > 0")
        view = view[written:]


def _get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


_DRAFT_COLUMNS = [
    "id", "status", "approval_state",
    "source", "canonical_title", "canonical_description",
    "item_facts_json", "pricing_json", "images_json",
    "renderings_json", "warnings_json", "metadata_json",
    "created_at", "updated_at", "approved_at", "archived_at",
]


def _row_to_dict(row) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i, c in enumerate(_DRAFT_COLUMNS):
        v = row[i]
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[c] = v
    return out


# ── Schema init (called from app/api/v1/router.py _inits list) ────────────────
def init_drafts_table() -> None:
    """Create tony_drafts if not present. Idempotent.

    Mirrors the SQL in db/migrations/20260528082612_create_tony_drafts.sql.
    The migration file is audit history; this function is what prod runs.
    """
    try:
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tony_drafts (
                        id BIGSERIAL PRIMARY KEY,
                        status TEXT NOT NULL DEFAULT 'draft_generated',
                        approval_state TEXT NOT NULL DEFAULT 'pending_review',
                        source TEXT NOT NULL DEFAULT 'photo_session',
                        canonical_title TEXT,
                        canonical_description TEXT,
                        item_facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        pricing_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        images_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        renderings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        approved_at TIMESTAMPTZ,
                        archived_at TIMESTAMPTZ,
                        CHECK (status IN ('draft_generated', 'needs_review', 'approved', 'submitted', 'archived', 'rejected')),
                        CHECK (approval_state IN ('pending_review', 'approved', 'rejected', 'needs_changes')),
                        CHECK (
                            status NOT IN ('approved', 'submitted')
                            OR approval_state = 'approved'
                        )
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_drafts_status_created
                        ON tony_drafts (status, created_at DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_drafts_approval_state
                        ON tony_drafts (approval_state)
                """)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[DRAFTS] init_drafts_table failed: {e}")


# ── CRUD ──────────────────────────────────────────────────────────────────────
def create_draft(
    canonical_title: Optional[str] = None,
    canonical_description: Optional[str] = None,
    item_facts: Optional[Dict] = None,
    pricing: Optional[Dict] = None,
    images: Optional[List[Dict]] = None,
    renderings: Optional[Dict] = None,
    warnings: Optional[List[str]] = None,
    metadata: Optional[Dict] = None,
    source: str = "photo_session",
) -> Optional[int]:
    """INSERT a new tony_drafts row.

    Returns the new id on success, None on any failure. Initial status =
    'draft_generated' (default), approval_state = 'pending_review' (default).
    """
    try:
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tony_drafts (
                        source,
                        canonical_title, canonical_description,
                        item_facts_json, pricing_json, images_json,
                        renderings_json, warnings_json, metadata_json
                    ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                              %s::jsonb, %s::jsonb, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        source,
                        canonical_title,
                        canonical_description,
                        json.dumps(item_facts or {}, default=str),
                        json.dumps(pricing or {}, default=str),
                        json.dumps(images or [], default=str),
                        json.dumps(renderings or {}, default=str),
                        json.dumps(warnings or [], default=str),
                        json.dumps(metadata or {}, default=str),
                    ),
                )
                return int(cur.fetchone()[0])
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="create_draft failed",
            error_class=type(e).__name__,
            error_message=str(e),
        )
        return None


def get_draft(draft_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a draft by id. Returns dict on success, None if not found or on error."""
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(_DRAFT_COLUMNS)} FROM tony_drafts WHERE id = %s",
                    (draft_id,),
                )
                row = cur.fetchone()
                return _row_to_dict(row) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="get_draft failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id},
        )
        return None


def list_drafts(limit: int = 20) -> List[Dict[str, Any]]:
    """Most-recent tony_drafts rows, newest first. Returns [] on failure.

    Cap on limit is 50 — the planner dispatcher uses this for chain-aware
    "review my latest draft" style goals, which only need enough rows to
    discriminate by description, not the full table.
    """
    try:
        capped = max(1, min(int(limit) if limit else 20, 50))
    except (TypeError, ValueError):
        capped = 20
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {', '.join(_DRAFT_COLUMNS)}
                    FROM tony_drafts
                    WHERE archived_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (capped,),
                )
                rows = cur.fetchall()
                return [_row_to_dict(r) for r in rows]
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="list_drafts failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"limit": limit},
        )
        return []


def update_images_json(draft_id: int, images: List[Dict]) -> bool:
    """Replace images_json on an existing draft row + bump updated_at.

    Returns True on success, False on any failure. Used by the from-photos
    endpoint after the empty draft row is created and images are staged
    onto the volume — the images_json handles can only be filled in once
    the draft_id is known (because the handle path embeds the draft_id).
    """
    try:
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tony_drafts
                    SET images_json = %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (json.dumps(images, default=str), draft_id),
                )
                return cur.rowcount > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="update_images_json failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id, "image_count": len(images)},
        )
        return False


def update_draft_fields(
    draft_id: int,
    canonical_title: Optional[str] = None,
    canonical_description: Optional[str] = None,
    item_facts: Optional[Dict] = None,
    pricing: Optional[Dict] = None,
    renderings: Optional[Dict] = None,
    warnings: Optional[List[str]] = None,
    status: Optional[str] = None,
) -> bool:
    """Update one or more fields on a draft row. Returns True on success,
    False on failure or if no row matched.

    Does NOT touch approval_state (human gate, separate endpoint) and does
    NOT touch images_json (use update_images_json for that).
    """
    try:
        sets = []
        params: List[Any] = []
        if canonical_title is not None:
            sets.append("canonical_title = %s")
            params.append(canonical_title)
        if canonical_description is not None:
            sets.append("canonical_description = %s")
            params.append(canonical_description)
        if item_facts is not None:
            sets.append("item_facts_json = %s::jsonb")
            params.append(json.dumps(item_facts, default=str))
        if pricing is not None:
            sets.append("pricing_json = %s::jsonb")
            params.append(json.dumps(pricing, default=str))
        if renderings is not None:
            sets.append("renderings_json = %s::jsonb")
            params.append(json.dumps(renderings, default=str))
        if warnings is not None:
            sets.append("warnings_json = %s::jsonb")
            params.append(json.dumps(warnings, default=str))
        if status is not None:
            sets.append("status = %s")
            params.append(status)

        if not sets:
            return False

        sets.append("updated_at = NOW()")
        params.append(draft_id)
        sql = f"UPDATE tony_drafts SET {', '.join(sets)} WHERE id = %s"

        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return cur.rowcount > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="update_draft_fields failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id},
        )
        return False


# ── Image staging + resolver ──────────────────────────────────────────────────
def get_photo_dir(draft_id: int) -> str:
    """Return the absolute directory where a draft's photos live on the volume."""
    return os.path.join(_STORAGE_BASE, _DRAFTS_SUBDIR, str(draft_id), "photos")


def resolve_image_path(image_entry: Dict[str, Any]) -> Optional[str]:
    """Turn a stored images_json entry back into a filesystem path.

    Validates storage type, joins against NOVA_DRAFT_STORAGE_BASE, then asserts
    the resolved real path stays under {STORAGE_BASE}/drafts/ — anything
    outside is rejected as a path-escape attempt and logged.

    Returns the resolved absolute path on success, None on any rejection.
    """
    try:
        if not isinstance(image_entry, dict):
            return None
        if image_entry.get("storage") != "railway_volume":
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.drafts",
                message="resolve_image_path: unsupported storage type",
                metadata={"storage": image_entry.get("storage")},
            )
            return None
        relative = image_entry.get("path")
        if not relative or not isinstance(relative, str):
            return None

        # Join + normalise. abspath collapses '..' segments without touching
        # the filesystem; realpath would resolve symlinks too, but we don't
        # expect symlinks here and abspath is sufficient for the escape guard.
        joined = os.path.abspath(os.path.join(_STORAGE_BASE, relative))
        drafts_root = os.path.abspath(os.path.join(_STORAGE_BASE, _DRAFTS_SUBDIR))

        # Guard: the resolved path MUST start with drafts_root + os.sep (or be
        # equal to drafts_root itself, though that wouldn't be a file). The
        # os.sep tail ensures '/data/draftsX/y' can't masquerade as inside
        # '/data/drafts'.
        if not (joined == drafts_root or joined.startswith(drafts_root + os.sep)):
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.drafts",
                message="resolve_image_path: path-escape attempt rejected",
                metadata={"requested_path": relative},
            )
            return None
        return joined
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="resolve_image_path failed",
            error_class=type(e).__name__,
            error_message=str(e),
        )
        return None


def stage_image_bytes(
    draft_id: int,
    image_id: str,
    image_bytes: bytes,
    ext: str,
) -> Optional[str]:
    """Write image bytes atomically to /data/drafts/{draft_id}/photos/{image_id}.{ext}.

    Returns the relative path (suitable for images_json.path) on success, None
    on any failure. The endpoint caller is responsible for delete-on-batch-
    failure cleanup (see drafts_selling endpoint).

    Input validation (defence in depth — public helper, can't trust callers):
    - `image_id` must match _SAFE_BASENAME_RE (no path separators, no '..',
      no leading dot). UUIDs pass. A malicious image_id like '../escape'
      would otherwise let stage_image_bytes write outside the photo dir.
    - `ext` must be in _VALID_EXTS after lstrip('.'). Anything else is
      rejected before any disk work.
    - The computed `final_path` is re-checked to be inside the draft's
      photo dir after `os.path.abspath` collapses any segments — paired
      defence against future call-site bugs.

    Atomic write: temp file in the same directory → write-all (loops over
    short writes) → fsync(file) → os.replace into final name → best-effort
    fsync(dir). This survives a mid-write crash without leaving a half-
    written final file visible. The write-all loop is essential because
    raw `os.write()` is allowed to perform partial writes without raising.
    """
    try:
        # 1. Input validation (rejects malicious callers + future bugs).
        if not isinstance(image_id, str) or not _SAFE_BASENAME_RE.fullmatch(image_id):
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.drafts",
                message="stage_image_bytes: image_id failed strict-basename validation",
                metadata={"draft_id": draft_id, "image_id_repr": repr(image_id)[:80]},
            )
            return None

        safe_ext = (ext or "").lstrip(".").lower()
        if safe_ext not in _VALID_EXTS:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.drafts",
                message="stage_image_bytes: ext not in allow-list",
                metadata={"draft_id": draft_id, "ext": safe_ext},
            )
            return None

        photo_dir = get_photo_dir(draft_id)
        final_name = f"{image_id}.{safe_ext}"
        final_path = os.path.abspath(os.path.join(photo_dir, final_name))

        # 2. Containment check on the resolved final_path. With the
        #    basename + ext validation above this is redundant in practice,
        #    but it's the same shape as resolve_image_path()'s guard and
        #    guarantees no escape if either validation is ever loosened.
        photo_dir_abs = os.path.abspath(photo_dir)
        if not (
            final_path == photo_dir_abs
            or final_path.startswith(photo_dir_abs + os.sep)
        ):
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.drafts",
                message="stage_image_bytes: final_path escaped photo_dir",
                metadata={"draft_id": draft_id, "image_id": image_id},
            )
            return None

        os.makedirs(photo_dir, exist_ok=True)
        tmp_path = final_path + ".tmp"

        # 3. Write the full payload — _write_all loops over short os.write().
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            _write_all(fd, image_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)

        os.replace(tmp_path, final_path)

        # 4. fsync the directory so the rename is durable on disk too.
        try:
            dir_fd = os.open(photo_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            # Non-fatal: rename already landed; dir fsync improves crash
            # safety but isn't required for correctness on most volumes.
            pass

        # 5. Return the path RELATIVE to NOVA_DRAFT_STORAGE_BASE for storage
        #    in images_json. Operators resolve via resolve_image_path().
        return os.path.join(_DRAFTS_SUBDIR, str(draft_id), "photos", final_name)
    except Exception as e:
        # Best-effort cleanup of any partial tmp file left behind so a retry
        # doesn't trip on stale state.
        try:
            tmp_candidate = locals().get("tmp_path")
            if tmp_candidate and os.path.exists(tmp_candidate):
                os.remove(tmp_candidate)
        except Exception:
            pass
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="stage_image_bytes failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id, "image_id": image_id, "bytes": len(image_bytes)},
        )
        return None


def delete_staged_images(draft_id: int) -> int:
    """Remove all staged images for a draft (used on ingress failure cleanup).

    Returns the count of files deleted. Never raises.
    """
    try:
        photo_dir = get_photo_dir(draft_id)
        if not os.path.isdir(photo_dir):
            return 0
        removed = 0
        for name in os.listdir(photo_dir):
            try:
                os.remove(os.path.join(photo_dir, name))
                removed += 1
            except Exception:
                # Best-effort cleanup; missing a file isn't fatal.
                pass
        try:
            os.rmdir(photo_dir)
        except Exception:
            pass
        return removed
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.WARNING,
            subsystem="selling.drafts",
            message="delete_staged_images failed (best-effort cleanup)",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id},
        )
        return 0


def delete_draft(draft_id: int) -> bool:
    """DELETE the draft row. Used by the from-photos endpoint when image
    staging fails mid-batch to roll back the empty placeholder row.

    Does NOT cascade to tony_selling_jobs (the draft_id link doesn't exist
    yet; when it lands it'll be ON DELETE RESTRICT to prevent orphans by
    accident).
    """
    try:
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tony_drafts WHERE id = %s", (draft_id,))
                return cur.rowcount > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.WARNING,
            subsystem="selling.drafts",
            message="delete_draft failed (rollback cleanup)",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id},
        )
        return False
