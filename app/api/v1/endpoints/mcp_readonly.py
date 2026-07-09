"""Authenticated read-only MCP-style endpoint."""

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.mcp_readonly import handle_jsonrpc, list_tools
from app.core.security import verify_token


router = APIRouter()


class McpJsonRpcRequest(BaseModel):
    jsonrpc: str = Field("2.0")
    id: Any = None
    method: str
    params: Dict[str, Any] | None = None


@router.get("/mcp/read-only/tools")
async def mcp_readonly_tools(_=Depends(verify_token)):
    return {"ok": True, **list_tools()}


@router.post("/mcp/read-only")
async def mcp_readonly_rpc(
    body: McpJsonRpcRequest,
    _=Depends(verify_token),
):
    return await handle_jsonrpc(body.model_dump())
