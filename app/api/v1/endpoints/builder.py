"""
Tony's Capability Builder endpoint.

Autonomous builds are staged for human review. Tony generates + validates
code and fires a proactive alert, but nothing is pushed to GitHub or
deployed until POST /builder/approve/{request_id} is called. Rejected
builds are deleted.

Routes:
  POST /builder/build                 — manually request a build (goes
                                        through the approval gate like
                                        any other)
  GET  /builder/status                — active-vs-gaps summary
  GET  /builder/pending               — list every pending row with code
  POST /builder/approve/{request_id}  — push + deploy a staged build
  POST /builder/reject/{request_id}   — delete a staged build
"""
import json
import os
import psycopg2
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token

router = APIRouter()


def _get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


@router.post("/builder/build")
async def build_new_capability(
    name: str,
    description: str,
    _=Depends(verify_token),
):
    """
    Manually request a capability build. Stages generated code for human
    review — does NOT deploy. The caller must approve via
    POST /builder/approve/{request_id} before anything reaches production.
    """
    from app.core.gap_detector import start_autonomous_build
    request_id = await start_autonomous_build(
        capability_name=name,
        description=description,
        user_message=f"manual build request: {description}",
    )
    if request_id <= 0:
        return {"ok": False, "error": "Failed to start staging — see server logs"}
    return {
        "ok": True,
        "request_id": request_id,
        "status": "pending_review",
        "note": (
            f"Staged for review. Code generation + validation is running "
            f"in the background (typically 30-90s). Inspect the generated "
            f"code via GET /api/v1/builder/pending. "
            f"Approve via POST /api/v1/builder/approve/{request_id} "
            f"or reject via POST /api/v1/builder/reject/{request_id}."
        ),
    }


@router.get("/builder/status")
async def builder_status(_=Depends(verify_token)):
    """Active capabilities and known gaps."""
    from app.core.capabilities import get_capabilities
    all_caps = get_capabilities() or []
    active = [c for c in all_caps if c.get("status") == "active"]
    not_built = [c for c in all_caps if c.get("status") == "not_built"]
    return {
        "active_capabilities": len(active),
        "gaps": len(not_built),
        "not_built": [c["name"] for c in not_built],
    }


@router.get("/builder/pending")
async def list_pending(_=Depends(verify_token)):
    """List all staged capability builds awaiting human approval, newest first."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, request_id, capability_name, capability_description,
               user_message, filename, module_name, generated_code,
               env_vars_needed, providers_used, validation_report, created_at
        FROM pending_capabilities
        WHERE status = 'pending'
        ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    out = []
    for r in rows:
        (pid, req_id, name, desc, umsg, fname, mod, code,
         ev_json, prov_json, valid_json, created) = r
        try:
            age_hours = round((datetime.utcnow() - created).total_seconds() / 3600.0, 2)
        except Exception:
            age_hours = None
        out.append({
            "pending_id": pid,
            "request_id": req_id,
            "capability_name": name,
            "capability_description": desc,
            "user_message": umsg,
            "filename": fname,
            "module_name": mod,
            "env_vars_needed": _safe_json_load(ev_json),
            "providers_used": _safe_json_load(prov_json),
            "validation_report": _safe_json_load(valid_json),
            "generated_code": code,
            "created_at": str(created),
            "age_hours": age_hours,
        })
    return {"ok": True, "count": len(out), "pending": out}


def _safe_json_load(s):
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


@router.post("/builder/approve/{request_id}")
async def approve_pending(request_id: int, _=Depends(verify_token)):
    """Approve a staged build: push to GitHub, wire router, deploy. Runs
    the post-deploy eval gate (auto-reverts on critical regression)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, capability_name, capability_description, filename,
               module_name, generated_code, env_vars_needed, providers_used, status
        FROM pending_capabilities
        WHERE request_id = %s
        ORDER BY id DESC LIMIT 1
    """, (request_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {"ok": False, "error": f"no pending capability for request_id={request_id}"}
    (pending_id, name, desc, filename, module_name, code,
     ev_json, prov_json, current_status) = row

    # Idempotent double-click handling
    if current_status == "deployed":
        cur.close()
        conn.close()
        return {"ok": True, "note": "already deployed", "request_id": request_id}
    if current_status == "approved":
        cur.close()
        conn.close()
        return {"ok": False, "error": "deploy already in progress for this request_id"}
    if current_status != "pending":
        cur.close()
        conn.close()
        return {"ok": False, "error": f"cannot approve — current status is {current_status}"}

    # Filename collision check — refuse rather than silently overwrite another pending
    cur.execute("""
        SELECT request_id FROM pending_capabilities
        WHERE filename = %s AND status IN ('pending', 'approved') AND id != %s
    """, (filename, pending_id))
    colliding = cur.fetchone()
    if colliding:
        cur.close()
        conn.close()
        return {
            "ok": False,
            "error": (f"filename {filename} has another pending entry "
                      f"(request_id={colliding[0]}); reject that one first"),
        }

    # Mark approved (intermediate status prevents a concurrent approve from pushing twice)
    cur.execute(
        "UPDATE pending_capabilities SET status='approved', decided_at=NOW() WHERE id=%s",
        (pending_id,),
    )
    conn.commit()
    cur.close()
    conn.close()

    # Reconstruct artifacts and deploy
    from app.core.capability_builder import deploy_capability_stage
    artifacts = {
        "filename": filename,
        "module_name": module_name,
        "code": code,
        "env_vars": _safe_json_load(ev_json),
        "providers_used": _safe_json_load(prov_json),
    }
    report = await deploy_capability_stage(name, desc, artifacts)

    # Finalise DB state based on deploy outcome
    conn = _get_conn()
    cur = conn.cursor()
    if report.get("success"):
        cur.execute("UPDATE pending_capabilities SET status='deployed' WHERE id=%s", (pending_id,))
        cur.execute("""
            UPDATE tony_capability_requests
            SET status='deployed', completed_at=NOW(), success=TRUE
            WHERE id=%s
        """, (request_id,))
        # Clear the review alert
        cur.execute(
            "UPDATE tony_alerts SET read=TRUE WHERE dedup_key=%s",
            (f"pending_build:{name}",),
        )
    else:
        err_note = (report.get("note") or report.get("error") or "deploy failed")[:500]
        cur.execute("""
            UPDATE pending_capabilities SET status='deploy_failed', decision_notes=%s
            WHERE id=%s
        """, (err_note, pending_id))
        cur.execute("""
            UPDATE tony_capability_requests
            SET status='deploy_failed', completed_at=NOW(), success=FALSE,
                last_error=%s
            WHERE id=%s
        """, (err_note, request_id))
    conn.commit()
    cur.close()
    conn.close()

    return {
        "ok": report.get("success", False),
        "request_id": request_id,
        "capability_name": name,
        "report": report,
    }


class RejectBody(BaseModel):
    reason: Optional[str] = None


@router.post("/builder/reject/{request_id}")
async def reject_pending(
    request_id: int,
    body: Optional[RejectBody] = None,
    _=Depends(verify_token),
):
    """Reject a staged build: delete the pending row, mark the originating
    request as rejected, clear the review alert."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, capability_name FROM pending_capabilities
        WHERE request_id=%s AND status='pending'
        ORDER BY id DESC LIMIT 1
    """, (request_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {"ok": False, "error": f"no pending capability for request_id={request_id}"}
    pending_id, name = row
    reason = (body.reason if body else None) or "no reason given"

    cur.execute("DELETE FROM pending_capabilities WHERE id=%s", (pending_id,))
    cur.execute("""
        UPDATE tony_capability_requests
        SET status='rejected', completed_at=NOW(), success=FALSE,
            last_error=%s
        WHERE id=%s
    """, (f"rejected: {reason}"[:500], request_id))
    cur.execute(
        "UPDATE tony_alerts SET read=TRUE WHERE dedup_key=%s",
        (f"pending_build:{name}",),
    )
    conn.commit()
    cur.close()
    conn.close()

    return {"ok": True, "rejected": request_id, "capability_name": name}
