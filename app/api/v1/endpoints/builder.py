"""
Tony's Capability Builder endpoint.
When Tony can't do something, he builds the capability himself.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.capability_builder import build_capability

router = APIRouter()

@router.post("/builder/build")
async def build_new_capability(
    name: str,
    description: str,
    _=Depends(verify_token)
):
    """
    Tell Tony what capability to build.
    He'll research, write the code, validate it, deploy it, and register it.
    name: short identifier e.g. "spotify", "facebook", "sms"
    description: what it should do e.g. "Control Spotify playback via Spotify Web API"
    """
    result = await build_capability(name, description)
    return result

@router.get("/builder/status")
async def builder_status(_=Depends(verify_token)):
    """Check what capabilities Tony has auto-built."""
    from app.core.capabilities import get_capabilities
    auto_built = [c for c in get_capabilities() if c["status"] == "active"]
    not_built = [c for c in get_capabilities() if c["status"] == "not_built"]
    return {
        "active_capabilities": len(auto_built),
        "gaps": len(not_built),
        "not_built": [c["name"] for c in not_built]
    }
