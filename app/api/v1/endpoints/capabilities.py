from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.capabilities import get_capabilities, log_capability_gap

router = APIRouter()

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
