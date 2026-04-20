"""
Codebase sync endpoint.
Receives files from Android app and stores them for Tony's reference.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
from app.core.security import verify_token
from app.core.codebase_sync import (
    store_files, get_codebase_summary, search_codebase,
    get_codebase_stats, init_codebase_table
)

router = APIRouter()


class CodebaseFile(BaseModel):
    path: str
    content: str


class CodebaseSyncRequest(BaseModel):
    files: List[CodebaseFile]
    source: str = "frontend"  # frontend or backend


@router.post("/codebase/sync")
async def sync_codebase(req: CodebaseSyncRequest, _=Depends(verify_token)):
    """Receive files from Android app and store them."""
    init_codebase_table()
    file_map = {f.path: f.content for f in req.files}
    result = store_files(req.source, file_map)
    return result


@router.get("/codebase/summary")
async def codebase_summary(_=Depends(verify_token)):
    """Get summary of what Tony knows about his codebase."""
    summary = get_codebase_summary(max_chars=5000)
    stats = get_codebase_stats()
    return {"ok": True, "summary": summary, "stats": stats}


@router.get("/codebase/search")
async def search(query: str, limit: int = 5, _=Depends(verify_token)):
    """Search codebase for a term."""
    results = search_codebase(query, limit=limit)
    return {"ok": True, "query": query, "results": results, "count": len(results)}


@router.get("/codebase/stats")
async def stats(_=Depends(verify_token)):
    """How many files Tony has stored, per source."""
    return get_codebase_stats()
