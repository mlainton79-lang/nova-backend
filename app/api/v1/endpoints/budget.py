"""Budget monitoring + freeze/unfreeze endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.budget_guard import (
    get_usage, get_budget_state, check_budget_and_freeze_if_needed, unfreeze
)

router = APIRouter()


@router.get("/budget")
async def status(_=Depends(verify_token)):
    state = get_budget_state()
    return {
        "ok": True,
        "frozen": state.get("frozen", False),
        "reason": state.get("freeze_reason"),
        "limits": {
            "hourly_calls": state.get("hourly_limit"),
            "daily_calls": state.get("daily_limit"),
            "hourly_cost": state.get("hourly_cost_limit"),
            "daily_cost": state.get("daily_cost_limit"),
        },
        "usage": {
            "last_hour": get_usage(1),
            "last_24h": get_usage(24),
        },
    }


@router.post("/budget/check")
async def check(_=Depends(verify_token)):
    """Force a check — freezes if over limits."""
    return check_budget_and_freeze_if_needed()


@router.post("/budget/unfreeze")
async def unfreeze_endpoint(_=Depends(verify_token)):
    return unfreeze()
