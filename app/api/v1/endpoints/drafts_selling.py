"""Selling-draft endpoints.

Design contract:
  nova-docs/ops/evidence/2026-05-28/SESSION_BRIEF_draft_pipeline_design.md

Routes:
- POST /api/v1/drafts/from-photos    (verify_token)  → stage images,
                                                       run vision pipeline once,
                                                       INSERT tony_drafts,
                                                       return {ok, draft_id, draft}

This file is intentionally NOT named drafts.py because the existing
app/api/v1/endpoints/drafts.py is Tony's EMAIL drafts endpoint (Gmail
reply drafts). The selling pipeline gets its own module to avoid the
collision.

Image-ingress contract:
- Limits: 1–12 images per request, 10MB per image (after base64 decode),
  80MB per request total. MIME sniffed against an allow-list.
- Atomic, all-or-nothing: every accepted image is decoded, hashed, written
  to /data/drafts/{draft_id}/photos/{image_id}.{ext} via temp+fsync+replace.
  On any failure mid-batch, every staged file is deleted, the draft row is
  removed, and the endpoint returns a non-2xx response. No partial draft
  with missing images is ever persisted.

Vision pipeline: calls the existing app/core/vinted.py full_listing_pipeline
ONCE with platform='vinted'. Despite the platform argument, what we keep is
the canonical (marketplace-neutral) item facts + the canonical title/desc
that the Vinted prompt happens to produce. Platform-specific re-rendering
for eBay etc. is a follow-up brick.
"""

import base64
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.core.security import verify_token
from app.core.vinted import full_listing_pipeline
from app.observability import EVENT_TYPES, EventSeverity, record_run_event
from app.selling import drafts as drafts_mod

log = logging.getLogger(__name__)

router = APIRouter()


# ── Limits ───────────────────────────────────────────────────────────────────
_MIN_IMAGES = 1
_MAX_IMAGES = 12
_MAX_IMAGE_BYTES = 10 * 1024 * 1024          # 10 MB per image (post-decode)
_MAX_REQUEST_BYTES = 80 * 1024 * 1024        # 80 MB total per request

# MIME → file extension allow-list. eBay Picture Services + Vinted both
# happily consume these. anything else is rejected at ingress.
_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Magic-byte sniffing — defence in depth against caller-supplied MIME lies.
def _sniff_mime(b: bytes) -> Optional[str]:
    if len(b) < 12:
        return None
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None


# ── Request shape ────────────────────────────────────────────────────────────
class ImageItem(BaseModel):
    base64: str
    mime: str = "image/jpeg"


class FromPhotosRequest(BaseModel):
    """Photo(s) in → draft out.

    Accepts EITHER a single image (image_base64 + image_mime) OR a list of
    images via `images`. Matches the existing /vinted/create-listing shape
    so Android can swap endpoints without restructuring the payload.
    """
    image_base64: Optional[str] = None
    image_mime: str = "image/jpeg"
    images: Optional[List[ImageItem]] = None
    condition: str = "good"
    user_notes: str = ""

    @model_validator(mode="after")
    def validate_image_input(self) -> "FromPhotosRequest":
        single = bool(self.image_base64)
        multi = self.images is not None and len(self.images) > 0
        if single and multi:
            raise ValueError("Provide either image_base64 or images, not both")
        if not single and not multi:
            raise ValueError("Provide either image_base64 or images")
        if multi and not (_MIN_IMAGES <= len(self.images) <= _MAX_IMAGES):
            raise ValueError(f"images must contain {_MIN_IMAGES}-{_MAX_IMAGES} items")
        return self


# ── Endpoint ─────────────────────────────────────────────────────────────────
@router.post("/drafts/from-photos")
async def create_draft_from_photos(
    req: FromPhotosRequest,
    _=Depends(verify_token),
):
    """Photo(s) in → persisted marketplace-agnostic draft out.

    All image staging is atomic and all-or-nothing. If anything fails before
    the vision pipeline runs, no draft row remains. If the vision pipeline
    fails after staging, the draft row + warnings are kept (the existing
    pipeline already returns deterministic fallbacks; we record the warning
    tokens in warnings_json and surface them to the caller).
    """
    # 1. Normalise to a uniform list of {base64, mime}.
    if req.image_base64:
        raw_items = [{"base64": req.image_base64, "mime": req.image_mime}]
    else:
        raw_items = [img.model_dump() for img in req.images]

    # 2. Decode + sniff + hash + budget. We DO NOT touch disk until every
    #    image in the request has passed validation. Disk staging is
    #    deferred until after the draft row is created so the path can
    #    include the new draft_id.
    decoded: List[dict] = []
    total_bytes = 0

    def _reject(ordinal: int, reason: str, status_code: int, detail: str, **extra) -> None:
        """Log a WARNING run_event for a deliberate client-input reject, then
        raise HTTPException. Metadata stays minimal — ordinal + reason + small
        scalars only — never the image bytes themselves.

        Coverage of these explicit-reject paths was promised by the commit
        note; pre-Codex review they raised without an event row, which made
        ingress rejects invisible in tony_run_events (codex-review-drafts-
        brick.md finding 3).
        """
        record_run_event(
            event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
            severity=EventSeverity.WARNING,
            subsystem="selling.drafts",
            message=f"from-photos: ingress reject ({reason})",
            metadata={"ordinal": ordinal, "reason": reason, **extra},
        )
        raise HTTPException(status_code=status_code, detail=detail)

    for ordinal, item in enumerate(raw_items):
        try:
            raw_b64 = item.get("base64") or ""
            claimed_mime = (item.get("mime") or "").lower()
            if claimed_mime not in _MIME_TO_EXT:
                _reject(
                    ordinal, "unsupported_mime",
                    status_code=415,
                    detail=f"image {ordinal}: unsupported mime {claimed_mime!r}",
                    claimed_mime=claimed_mime,
                )
            try:
                image_bytes = base64.b64decode(raw_b64, validate=True)
            except Exception:
                _reject(
                    ordinal, "invalid_base64",
                    status_code=400,
                    detail=f"image {ordinal}: invalid base64",
                )

            size = len(image_bytes)
            if size == 0:
                _reject(
                    ordinal, "empty_decode",
                    status_code=400,
                    detail=f"image {ordinal}: empty after decode",
                )
            if size > _MAX_IMAGE_BYTES:
                _reject(
                    ordinal, "per_image_byte_limit",
                    status_code=413,
                    detail=f"image {ordinal}: {size} bytes exceeds per-image limit {_MAX_IMAGE_BYTES}",
                    size_bytes=size, limit=_MAX_IMAGE_BYTES,
                )
            total_bytes += size
            if total_bytes > _MAX_REQUEST_BYTES:
                _reject(
                    ordinal, "request_byte_budget",
                    status_code=413,
                    detail=f"request exceeds {_MAX_REQUEST_BYTES} byte budget",
                    total_bytes=total_bytes, limit=_MAX_REQUEST_BYTES,
                )

            sniffed = _sniff_mime(image_bytes)
            if sniffed is None or sniffed not in _MIME_TO_EXT:
                _reject(
                    ordinal, "magic_byte_sniff_failed",
                    status_code=415,
                    detail=f"image {ordinal}: bytes don't match a supported image format",
                    sniffed=sniffed,
                )
            # Defence in depth: if the caller's claimed mime disagrees with
            # the sniffed mime, trust the sniff (extension follows the sniff).
            effective_mime = sniffed
            ext = _MIME_TO_EXT[effective_mime]

            decoded.append({
                "ordinal": ordinal,
                "bytes": image_bytes,
                "mime": effective_mime,
                "ext": ext,
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
                "size_bytes": size,
            })
        except HTTPException:
            raise
        except Exception as e:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.ERROR,
                subsystem="selling.drafts",
                message="from-photos: ingress validation failed",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"ordinal": ordinal},
            )
            raise HTTPException(
                status_code=400,
                detail=f"image {ordinal}: validation error",
            )

    # 3. Create the empty draft row so we have an id to stage paths under.
    draft_id = drafts_mod.create_draft(source="photo_session")
    if not draft_id:
        raise HTTPException(
            status_code=500,
            detail="failed to create draft row (see selling.drafts logs)",
        )

    # 4. Stage every image to disk atomically. On ANY failure, delete already-
    #    staged files + delete the draft row, then surface the failure.
    images_json: List[dict] = []
    try:
        for entry in decoded:
            image_id = str(uuid.uuid4())
            relative_path = drafts_mod.stage_image_bytes(
                draft_id=draft_id,
                image_id=image_id,
                image_bytes=entry["bytes"],
                ext=entry["ext"],
            )
            if not relative_path:
                # stage_image_bytes already logged via record_run_event.
                raise RuntimeError(f"stage_image_bytes returned None for image {entry['ordinal']}")
            images_json.append({
                "id": image_id,
                "storage": "railway_volume",
                "path": relative_path,
                "mime": entry["mime"],
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
                "role": "primary" if entry["ordinal"] == 0 else "secondary",
                "ordinal": entry["ordinal"],
                "source": "android_base64",
                "api_path": f"/api/v1/drafts/{draft_id}/images/{image_id}",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        # Roll back: delete every staged file + the placeholder draft row.
        drafts_mod.delete_staged_images(draft_id)
        drafts_mod.delete_draft(draft_id)
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="from-photos: image staging failed mid-batch; rolled back",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id, "staged_so_far": len(images_json)},
        )
        raise HTTPException(
            status_code=500,
            detail="image staging failed; no draft persisted",
        )

    # 5. Persist the images_json handles onto the draft row.
    if not drafts_mod.update_images_json(draft_id, images_json):
        drafts_mod.delete_staged_images(draft_id)
        drafts_mod.delete_draft(draft_id)
        raise HTTPException(
            status_code=500,
            detail="failed to persist image handles; rolled back",
        )

    # 6. Run the vision pipeline ONCE. We hand it the decoded base64 because
    #    the existing pipeline takes base64; the draft-side stable handles
    #    are separate (canonical storage), not what Gemini sees. This avoids
    #    rewriting full_listing_pipeline for now.
    pipeline_images = [
        {"base64": base64.b64encode(entry["bytes"]).decode(), "mime": entry["mime"]}
        for entry in decoded
    ]
    try:
        result = await full_listing_pipeline(
            platform="vinted",
            condition=req.condition,
            user_notes=req.user_notes,
            images=pipeline_images,
        )
    except Exception as e:
        # The existing pipeline catches its own exceptions and returns
        # _fallback'd values, so a raise here is unexpected. Treat as a soft
        # failure: persist what we have (just images + warnings), don't
        # roll back. The draft is recoverable manually.
        record_run_event(
            event_type=EVENT_TYPES["PROVIDER_ERROR"],
            severity=EventSeverity.ERROR,
            subsystem="selling.drafts",
            message="from-photos: vision pipeline raised unexpectedly",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"draft_id": draft_id},
        )
        drafts_mod.update_draft_fields(
            draft_id,
            warnings=["vision_pipeline_raised"],
            status="needs_review",
        )
        out = drafts_mod.get_draft(draft_id)
        return {"ok": False, "draft_id": draft_id, "draft": out, "error": "vision pipeline failed; draft kept"}

    # 7. Spread the pipeline output into the right JSONB columns + advance
    #    status to needs_review (machine transition, no human gate involved).
    item = result.get("item") or {}
    listing = result.get("listing") or {}
    prices = result.get("prices") or {}
    pipeline_warnings = list(result.get("warnings") or [])

    canonical_title = listing.get("title")
    canonical_description = listing.get("description")

    pricing = {
        "suggested_uk_resale_price": item.get("suggested_uk_resale_price"),
        "price_reasoning": item.get("price_reasoning"),
        "research": prices,
    }

    # Renderings: store the as-generated text under the vinted slot. eBay
    # adapter lands in a follow-up brick and will populate renderings.ebay
    # at job-creation time.
    renderings = {
        "vinted": {
            "title": listing.get("title"),
            "description": listing.get("description"),
            "price": listing.get("suggested_price"),
            "condition": listing.get("condition"),
            "category_suggestion": listing.get("category_suggestion"),
            "parcel_size": listing.get("parcel_size") or item.get("parcel_size"),
            "tips": listing.get("tips") or [],
            "adapter_status": "ready",
        },
    }

    ok = drafts_mod.update_draft_fields(
        draft_id,
        canonical_title=canonical_title,
        canonical_description=canonical_description,
        item_facts=item,
        pricing=pricing,
        renderings=renderings,
        warnings=pipeline_warnings,
        status="needs_review",
    )
    if not ok:
        # Row exists but the update failed for some reason. Surface and
        # leave the draft intact for inspection.
        raise HTTPException(
            status_code=500,
            detail="draft created and images staged, but pipeline-output persist failed; see selling.drafts logs",
        )

    out = drafts_mod.get_draft(draft_id)
    return {
        "ok": True,
        "draft_id": draft_id,
        "draft": out,
        "warnings": pipeline_warnings,
    }
