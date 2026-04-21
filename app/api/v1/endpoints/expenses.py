"""
Expense tracking endpoints — receipt photo → structured + queryable spending.
"""
from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import base64
from app.core.security import verify_token
from app.core.receipt_extractor import (
    extract_from_image, save_expense,
    get_expense_summary, list_recent_expenses
)

router = APIRouter()


class ExtractReceiptRequest(BaseModel):
    image_base64: str
    save: bool = True


@router.post("/expenses/extract")
async def extract(req: ExtractReceiptRequest, _=Depends(verify_token)):
    """Extract structured data from a receipt photo."""
    data = await extract_from_image(req.image_base64)
    if "error" in data:
        return {"ok": False, "error": data["error"], "data": data}
    saved_id = None
    if req.save:
        saved_id = save_expense(data, req.image_base64)
    return {"ok": True, "data": data, "saved_id": saved_id}


@router.get("/expenses/summary")
async def summary(days: int = 30, _=Depends(verify_token)):
    """Spending summary: total, by category, top merchants."""
    return {"ok": True, **get_expense_summary(days=days)}


@router.get("/expenses")
async def list_recent(limit: int = 20, _=Depends(verify_token)):
    """List recent expenses."""
    return {"ok": True, "expenses": list_recent_expenses(limit=limit)}


class VerifyRequest(BaseModel):
    expense_id: int
    verified: bool = True


@router.post("/expenses/verify")
async def verify(req: VerifyRequest, _=Depends(verify_token)):
    """Mark an expense as verified (Matthew confirms extraction was correct)."""
    import os, psycopg2
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("UPDATE tony_expenses SET verified = %s WHERE id = %s",
                    (req.verified, req.expense_id))
        cur.close()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
