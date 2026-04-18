"""Handover endpoint — live system state."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.handover import generate_live_handover

router = APIRouter()

@router.get("/handover")
async def get_handover(_=Depends(verify_token)):
    """Get live system state — accurate picture of what Tony has right now."""
    return generate_live_handover()
