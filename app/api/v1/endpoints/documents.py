"""Document memory endpoints — semantic search over uploaded documents."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.core.document_memory import (
    ingest_document, search_documents, list_documents, delete_document
)

router = APIRouter()


class IngestRequest(BaseModel):
    full_text: str
    doc_name: Optional[str] = ""
    doc_type: Optional[str] = "unknown"
    source: Optional[str] = "upload"


@router.post("/documents/ingest")
async def ingest(req: IngestRequest, _=Depends(verify_token)):
    return await ingest_document(
        full_text=req.full_text,
        doc_name=req.doc_name,
        doc_type=req.doc_type,
        source=req.source,
    )


class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5


@router.post("/documents/search")
async def search(req: SearchRequest, _=Depends(verify_token)):
    results = await search_documents(req.query, top_k=req.top_k or 5)
    return {"ok": True, "results": results}


@router.get("/documents")
async def list_all(limit: int = 20, _=Depends(verify_token)):
    return {"ok": True, "documents": list_documents(limit)}


@router.delete("/documents/{doc_id}")
async def delete(doc_id: int, _=Depends(verify_token)):
    ok = delete_document(doc_id)
    return {"ok": ok}
