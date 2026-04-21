"""
Endpoints for inspecting Tony's fact store.
Gives visibility into what structured memory he's built up.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import os
import psycopg2
from app.core.security import verify_token
from app.core.fact_extractor import get_facts_about, extract_facts, save_facts

router = APIRouter()


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


@router.get("/facts")
async def list_facts(subject: str = "Matthew", limit: int = 50,
                     _=Depends(verify_token)):
    """List facts Tony has extracted about someone/something."""
    facts = get_facts_about(subject, limit=limit)
    return {"ok": True, "subject": subject, "count": len(facts), "facts": facts}


@router.get("/facts/all")
async def all_facts(limit: int = 100, _=Depends(verify_token)):
    """List all active facts (not superseded)."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, subject, predicate, object, confidence,
                   confirmation_count, source, last_confirmed_at
            FROM tony_facts
            WHERE superseded_by IS NULL
            ORDER BY confirmation_count DESC, confidence DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {
            "ok": True,
            "count": len(rows),
            "facts": [
                {"id": r[0], "subject": r[1], "predicate": r[2],
                 "object": r[3], "confidence": r[4],
                 "confirmation_count": r[5], "source": r[6],
                 "last_confirmed_at": str(r[7])}
                for r in rows
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


class DeleteFactRequest(BaseModel):
    fact_id: int


@router.post("/facts/delete")
async def delete_fact(req: DeleteFactRequest, _=Depends(verify_token)):
    """Mark a fact as superseded (soft delete)."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("UPDATE tony_facts SET superseded_by = -1 WHERE id = %s",
                    (req.fact_id,))
        cur.close()
        conn.close()
        return {"ok": True, "deleted": req.fact_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class TestExtractRequest(BaseModel):
    user_message: str
    assistant_reply: str
    save: bool = False


@router.post("/facts/extract")
async def test_extract(req: TestExtractRequest, _=Depends(verify_token)):
    """Test fact extraction on a specific turn without saving (unless save=True)."""
    facts = await extract_facts(req.user_message, req.assistant_reply)
    if req.save and facts:
        save_facts(facts)
    return {"ok": True, "extracted": facts, "saved": req.save}
