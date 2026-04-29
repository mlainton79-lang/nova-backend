from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import psycopg2
from app.core.security import verify_token
from app.core.capabilities import (
    get_capabilities,
    log_capability_gap,
    create_capability,
    update_capability,
)

router = APIRouter()


class CreateCapabilityRequest(BaseModel):
    name: str
    description: str
    status: str = "active"
    runner: Optional[str] = None
    endpoint: Optional[str] = None
    risk_level: str = "low"
    approval_required: bool = False
    cost_type: str = "free"
    inputs: Optional[dict] = None
    outputs: Optional[dict] = None
    notes: Optional[str] = None


class UpdateCapabilityRequest(BaseModel):
    status: Optional[str] = None
    endpoint: Optional[str] = None
    runner: Optional[str] = None
    risk_level: Optional[str] = None
    approval_required: Optional[bool] = None
    cost_type: Optional[str] = None
    last_tested: Optional[str] = None
    last_result: Optional[str] = None
    failure_notes: Optional[str] = None
    notes: Optional[str] = None
    description: Optional[str] = None


@router.get("/capabilities")
async def list_capabilities(_=Depends(verify_token)):
    return {"capabilities": get_capabilities()}

@router.get("/capabilities/active")
async def active_capabilities(_=Depends(verify_token)):
    return {"capabilities": get_capabilities(status="active")}

@router.get("/capabilities/gaps")
async def capability_gaps(_=Depends(verify_token)):
    return {"capabilities": get_capabilities(status="not_built")}

@router.post("/capabilities/gap")
async def report_gap(request: str, proposed_solution: str = None, _=Depends(verify_token)):
    log_capability_gap(request, proposed_solution)
    return {"logged": True}


@router.post("/capabilities")
async def create_capability_endpoint(body: CreateCapabilityRequest, _=Depends(verify_token)):
    try:
        new_id = create_capability(
            name=body.name,
            description=body.description,
            status=body.status,
            runner=body.runner,
            endpoint=body.endpoint,
            risk_level=body.risk_level,
            approval_required=body.approval_required,
            cost_type=body.cost_type,
            inputs=body.inputs,
            outputs=body.outputs,
            notes=body.notes,
        )
        return {"ok": True, "id": new_id}
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"Capability '{body.name}' already exists. Use PATCH to update.")
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Capability '{body.name}' already exists. Use PATCH to update.")


@router.patch("/capabilities/{name}")
async def update_capability_endpoint(name: str, body: UpdateCapabilityRequest, _=Depends(verify_token)):
    fields = body.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = update_capability(name=name, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Capability '{name}' not found")

    return {"ok": True, "updated": list(fields.keys())}
