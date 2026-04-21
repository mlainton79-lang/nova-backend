"""Unified retrieval endpoint — search across all Tony's memory sources."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.unified_retrieval import unified_search, format_unified_results

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 8


@router.post("/retrieval/search")
async def search(req: SearchRequest, _=Depends(verify_token)):
    results = await unified_search(req.query, top_k=min(req.top_k, 20))
    return {"ok": True, "count": len(results), "results": results,
            "formatted": format_unified_results(results)}
