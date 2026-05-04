"""
Vinted job endpoints — create / read / cancel / publish-confirm / retry.

Job creation accepts multipart/form-data (draft fields + photos).
Photos are staged to /data/vinted_jobs/{job_id}/photos/. The Playwright
worker (vinted_worker/operator.py) reads from the same path on the
mounted Railway volume.

Triggering the worker is OUT OF SCOPE for this endpoint module — the
worker is a separate Railway service invoked manually with the job_id.
A future commit may add an auto-trigger via Railway API.
"""
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from app.core.security import verify_token
from app.core import vinted_jobs as jobs_mod
from app.core import pending_actions

router = APIRouter()

# Same volume path as vinted_worker/config.py.
PHOTO_BASE = os.environ.get("PHOTO_BASE", "/data/vinted_jobs")


def _photo_dir(job_id: int) -> str:
    return os.path.join(PHOTO_BASE, str(job_id), "photos")


@router.post("/vinted/jobs")
async def create_vinted_job(
    title: str = Form(...),
    description: str = Form(""),
    brand: str = Form(""),
    condition: str = Form(""),
    category: str = Form(""),
    price: str = Form(""),
    item_name: str = Form(""),
    draft_id: Optional[str] = Form(None),
    source_android_draft_id: Optional[str] = Form(None),
    account: str = Form("default"),
    photos: List[UploadFile] = File(default=[]),
    _=Depends(verify_token),
):
    """
    Create a Vinted fill-and-stop job. Stages photos to the volume,
    inserts a tony_vinted_jobs row, returns {ok, job_id}.

    The worker is NOT auto-triggered — invoke it manually:
        python -m vinted_worker.operator <job_id>
    """
    metadata = {
        "title": title,
        "description": description,
        "brand": brand,
        "condition": condition,
        "category": category,
        "price": price,
    }
    name = item_name.strip() or title.strip() or "untitled"

    job_id = jobs_mod.create_job(
        item_name=name,
        metadata=metadata,
        draft_id=draft_id,
        source_android_draft_id=source_android_draft_id,
        account=account,
    )
    if not job_id:
        raise HTTPException(status_code=500, detail="Could not create job row")

    # Stage photos onto the volume.
    photo_dir = _photo_dir(job_id)
    try:
        os.makedirs(photo_dir, exist_ok=True)
    except Exception as e:
        return {"ok": False, "job_id": job_id,
                "error": f"could not create photo dir: {e}"}

    saved = []
    for i, upload in enumerate(photos or []):
        if not upload or not upload.filename:
            continue
        # Sanitise filename — keep extension, drop path.
        base = os.path.basename(upload.filename)
        # Prefix index so order matches upload order on disk.
        target_name = f"{i:02d}_{base}"
        target = os.path.join(photo_dir, target_name)
        try:
            data = await upload.read()
            with open(target, "wb") as f:
                f.write(data)
            saved.append(target_name)
        except Exception as e:
            jobs_mod.append_event(job_id, "photo_stage_failed",
                                  f"file={base} err={type(e).__name__}")

    jobs_mod.append_event(
        job_id,
        "job_created",
        f"item_name={name} photos_staged={len(saved)}",
    )

    return {
        "ok": True,
        "job_id": job_id,
        "item_name": name,
        "photos_staged": len(saved),
        "photo_dir": photo_dir,
        "next_step": (
            f"Trigger worker: python -m vinted_worker.operator {job_id}"
        ),
    }


@router.get("/vinted/jobs/{job_id}")
async def get_vinted_job(job_id: int, _=Depends(verify_token)):
    job = jobs_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    events = jobs_mod.list_recent_events(job_id, limit=50)
    return {"ok": True, "job": job, "events": events}


@router.get("/vinted/jobs")
async def list_vinted_jobs(
    limit: int = 20,
    status: Optional[str] = None,
    _=Depends(verify_token),
):
    jobs = jobs_mod.list_recent_jobs(limit=limit, status=status)
    return {"ok": True, "jobs": jobs, "count": len(jobs)}


@router.post("/vinted/jobs/{job_id}/cancel")
async def cancel_vinted_job(job_id: int, _=Depends(verify_token)):
    job = jobs_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] in ("published_by_matthew", "cancelled"):
        return {"ok": False, "error": f"job already in terminal state: {job['status']}"}
    ok = jobs_mod.mark_cancelled(job_id)
    jobs_mod.append_event(job_id, "cancelled", "cancelled by Matthew via API")
    return {"ok": ok, "job_id": job_id, "status": "cancelled"}


@router.post("/vinted/jobs/{job_id}/published")
async def confirm_vinted_published(job_id: int, _=Depends(verify_token)):
    """
    Matthew confirms he tapped Publish in Vinted and the listing is live.
    """
    job = jobs_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] == "published_by_matthew":
        return {"ok": True, "job_id": job_id, "status": "already_confirmed"}
    ok = jobs_mod.mark_published_by_matthew(job_id)
    jobs_mod.append_event(
        job_id, "published_confirmed",
        "Matthew confirmed manual publish via API",
    )
    return {"ok": ok, "job_id": job_id, "status": "published_by_matthew"}


@router.post("/vinted/jobs/{job_id}/retry")
async def retry_vinted_job(job_id: int, _=Depends(verify_token)):
    """
    Reset a requires_human / error job back to queued so the worker can
    be re-invoked. Photos and metadata are preserved.
    """
    job = jobs_mod.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] not in ("requires_human", "error", "safety_violation"):
        return {
            "ok": False,
            "error": f"retry only allowed from requires_human/error/safety_violation, current: {job['status']}",
        }
    jobs_mod.update_status(
        job_id,
        "queued",
        error_message=None,
        error_type=None,
    )
    jobs_mod.append_event(job_id, "retry_requested", "Matthew requested retry")
    return {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "next_step": (
            f"Trigger worker: python -m vinted_worker.operator {job_id}"
        ),
    }
