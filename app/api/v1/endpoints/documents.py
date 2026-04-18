"""
Tony's document generation endpoint.
Tony creates properly formatted PDF letters and documents.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.core.document_generator import tony_generate_document, tony_generate_custom_pdf
import base64

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


@router.get("/documents/fca-complaint")
async def fca_complaint_template(_=Depends(verify_token)):
    """Generate Tony's FCA complaint about Western Circle."""
    result = await tony_generate_document(
        document_type="FCA Complaint",
        context="""Write a COMPLETE, DETAILED formal complaint letter. Every ground must be fully argued. Do not truncate.
Matthew Lainton has a CCJ from Western Circle Ltd (trading as Cashfloat) for approximately £700.
Case reference: K9QZ4X9N.

Grounds for complaint:
1. Irresponsible lending — Western Circle failed to conduct adequate affordability assessments under FCA CONC 5.2
2. Failure to apply vulnerability rules — Matthew had a gambling addiction at the time, which Western Circle was or should have been aware of
3. Western Circle acknowledged vulnerability in correspondence but maintained their affordability checks were sufficient
4. Failure to apply forbearance and due consideration under CONC 7.3
5. Breach of Consumer Duty (PS22/9) — failure to act in consumer's best interests
6. Breach of FG21/1 (vulnerable customer guidance)

The complaint is addressed to the FCA and requests:
- Investigation into Western Circle's lending practices
- Review of the CCJ under reference K9QZ4X9N
- Appropriate regulatory action against Western Circle

Matthew wants the CCJ removed and compensation considered.
        """,
        recipient_name="Financial Conduct Authority",
        recipient_address="12 Endeavour Square\nLondon\nE20 1JN"
    )
    return result
