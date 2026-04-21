"""Repository intelligence endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.repository_intelligence import (
    ingest_recent_commits, recent_changes, hot_files,
    file_history, search_commits
)

router = APIRouter()


@router.post("/repo/ingest")
async def ingest(count: int = 100, _=Depends(verify_token)):
    return ingest_recent_commits(count=count)


@router.get("/repo/recent")
async def recent(days: int = 7, _=Depends(verify_token)):
    return {"ok": True, "commits": recent_changes(days)}


@router.get("/repo/hot-files")
async def hot(days: int = 14, top_n: int = 10, _=Depends(verify_token)):
    return {"ok": True, "files": hot_files(days, top_n)}


class FileHistoryRequest(BaseModel):
    file_path: str
    limit: int = 10


@router.post("/repo/file-history")
async def file_hist(req: FileHistoryRequest, _=Depends(verify_token)):
    return {"ok": True, "history": file_history(req.file_path, req.limit)}


class CommitSearchRequest(BaseModel):
    query: str
    limit: int = 10


@router.post("/repo/search")
async def search(req: CommitSearchRequest, _=Depends(verify_token)):
    return {"ok": True, "results": search_commits(req.query, req.limit)}
