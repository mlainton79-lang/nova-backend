"""
Tony's document generation endpoint.
Tony creates properly formatted PDF letters and documents.
General purpose - works for any company, any context.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.core.document_generator import tony_generate_document, tony_generate_custom_pdf

router = APIRouter()


class DocumentRequest(BaseModel):
    document_type: str
    context: str
    recipient_name: Optional[str] = ""
    recipient_address: Optional[str] = ""


class CustomPDFRequest(BaseModel):
    title: str
    content: str
    recipient_name: Optional[str] = ""
    recipient_address: Optional[str] = ""


class EmailResponseRequest(BaseModel):
    company: str
    recipient_name: Optional[str] = ""
    recipient_address: Optional[str] = ""
    email_query: Optional[str] = ""
    intent: Optional[str] = ""


@router.post("/documents/generate")
async def generate_document(req: DocumentRequest, _=Depends(verify_token)):
    """Tony generates a document using AI then formats as PDF."""
    result = await tony_generate_document(
        document_type=req.document_type,
        context=req.context,
        recipient_name=req.recipient_name,
        recipient_address=req.recipient_address
    )
    return result


@router.post("/documents/custom")
async def custom_pdf(req: CustomPDFRequest, _=Depends(verify_token)):
    """Format provided content as a PDF."""
    result = await tony_generate_custom_pdf(
        title=req.title,
        content=req.content,
        recipient_name=req.recipient_name,
        recipient_address=req.recipient_address
    )
    return result


@router.post("/documents/from-emails")
async def generate_from_emails(req: EmailResponseRequest, _=Depends(verify_token)):
    """
    Tony reads all emails about a company and drafts a formal response letter.
    This is the general purpose endpoint - works for any company.
    """
    from app.core.gmail_service import deep_search_all_accounts

    # Search all Gmail accounts for emails related to this company
    query = req.email_query or req.company
    emails = await deep_search_all_accounts(query, max_per_account=50)

    if not emails:
        return {"ok": False, "error": f"No emails found relating to {req.company}"}

    # Build email summary for context
    email_summary = f"Emails found relating to {req.company}:\n\n"
    for i, e in enumerate(emails[:20], 1):
        email_summary += f"[{i}] {e.get('date', '')[:16]} | From: {e.get('from', '')} | Subject: {e.get('subject', '')}\n"
        if e.get('snippet'):
            email_summary += f"    Preview: {e.get('snippet', '')[:200]}\n"
        email_summary += "\n"

    context = f"""Write a COMPLETE, DETAILED formal letter. Do not truncate. Every point must be fully argued.

Company being written to: {req.company}
Matthew's intent: {req.intent or "formal response addressing all issues raised in correspondence"}

Email correspondence found:
{email_summary}

Matthew's full address: 61 Swangate, Brampton Bierlow, Rotherham, S63 6ER
Matthew's phone: 07735589035
Matthew's NI: JK985746C

Write a professional, firm letter addressing all relevant points from the correspondence.
Reference specific emails and dates where relevant. Be direct and factual."""

    result = await tony_generate_document(
        document_type=f"Letter to {req.company}",
        context=context,
        recipient_name=req.recipient_name or req.company,
        recipient_address=req.recipient_address
    )

    result["emails_found"] = len(emails)
    result["company"] = req.company
    return result
