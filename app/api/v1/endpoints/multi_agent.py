"""Multi-agent capability builder endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.multi_agent_builder import build_capability_multi_agent

router = APIRouter()


class BuildRequest(BaseModel):
    capability_name: str


@router.post("/multi-agent/build")
async def build(req: BuildRequest, _=Depends(verify_token)):
    """
    Run the multi-agent build pipeline.
    Returns the spec, code, critique, and validation results.
    Does NOT push to GitHub — review first.
    """
    return await build_capability_multi_agent(req.capability_name)
