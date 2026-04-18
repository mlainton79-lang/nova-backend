"""
Tony's Document Generator.

Tony can create properly formatted PDFs and letters.
Use cases:
- FCA complaint letter
- FOS complaint letter  
- Formal letters to Western Circle
- Vinted/eBay item descriptions
- Any document Matthew needs

Returns base64 PDF that can be downloaded or sent as email attachment.
"""
import os
import io
import re
import base64
import httpx
import json
from datetime import datetime
from typing import Optional, List, Dict

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _create_pdf(title: str, body_text: str, sender_name: str = "Matthew Lainton",
                sender_address: str = "Rotherham, South Yorkshire",
                recipient_name: str = "", recipient_address: str = "") -> bytes:
    """Create a properly formatted PDF letter."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_JUSTIFY

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2.5*cm,
        leftMargin=2.5*cm,
        topMargin=2.5*cm,
        bottomMargin=2.5*cm
    )

    styles = getSampleStyleSheet()
    
    normal = ParagraphStyle(
        'Normal',
        fontName='Times-Roman',
        fontSize=11,
        leading=17,
        spaceAfter=10,
        alignment=TA_JUSTIFY
    )
    bold = ParagraphStyle(
        'Bold',
        fontName='Times-Bold',
        fontSize=11,
        leading=17,
        spaceAfter=10
    )
    right = ParagraphStyle(
        'Right',
        fontName='Times-Roman',
        fontSize=11,
        leading=15,
        alignment=TA_RIGHT,
        spaceAfter=4
    )
    heading = ParagraphStyle(
        'Heading',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=18,
        spaceAfter=14,
        spaceBefore=10,
        textColor=colors.HexColor('#1a1a2e')
    )

    story = []

    # Sender details (top right)
    story.append(Paragraph(sender_name, right))
    if sender_address:
        for line in sender_address.split('\n'):
            story.append(Paragraph(line.strip(), right))
    story.append(Paragraph(datetime.now().strftime("%d %B %Y"), right))
    story.append(Spacer(1, 0.5*cm))

    # Recipient details (left)
    if recipient_name:
        story.append(Paragraph(recipient_name, normal))
    if recipient_address:
        for line in recipient_address.split('\n'):
            story.append(Paragraph(line.strip(), normal))
    story.append(Spacer(1, 0.5*cm))

    # Title/Subject
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(f"Re: {title}", heading))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    story.append(Spacer(1, 0.5*cm))

    # Body — split on double newlines for paragraphs
    paragraphs = re.split(r'\n\n+', body_text.strip())
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if para.startswith('**') and para.endswith('**'):
            story.append(Paragraph(para.replace('**', ''), bold))
        else:
            # Clean markdown
            para = re.sub(r'\*+', '', para)
            para = re.sub(r'#{1,6}\s', '', para)
            story.append(Paragraph(para, normal))
        story.append(Spacer(1, 0.1*cm))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Yours faithfully,", normal))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(sender_name, bold))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


async def tony_generate_document(
    document_type: str,
    context: str,
    recipient_name: str = "",
    recipient_address: str = ""
) -> Dict:
    """
    Tony generates a document using Gemini for content, then formats it as PDF.
    
    document_type: e.g. "FCA complaint", "FOS complaint", "formal letter", "demand letter"
    context: background info and what the document should say
    """
    if not GEMINI_API_KEY:
        return {"ok": False, "error": "Gemini API key not configured"}

    prompt = f"""You are Tony, Matthew Lainton's personal AI assistant. Generate a professional {document_type}.

Context and requirements:
{context}

Matthew's details:
- Name: Matthew Lainton
- Location: Rotherham, South Yorkshire
- Case reference (if legal): K9QZ4X9N (Western Circle CCJ)

Generate the complete letter body. Be formal, professional, and firm. British English throughout.
Do not include the date, sender address, or recipient address — those are handled separately.
Start directly with "Dear [appropriate salutation]," and end with "Yours faithfully," followed by a blank line for signature.

Important: Be specific, factual, and reference relevant regulations where applicable (FCA CONC rules, Consumer Duty, etc).
Write the complete letter now:"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3}
                }
            )
            r.raise_for_status()
            letter_body = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        # Create PDF
        pdf_bytes = _create_pdf(
            title=document_type,
            body_text=letter_body,
            sender_name="Matthew Lainton",
            sender_address="Rotherham\nSouth Yorkshire",
            recipient_name=recipient_name,
            recipient_address=recipient_address
        )

        pdf_b64 = base64.b64encode(pdf_bytes).decode()
        return {
            "ok": True,
            "pdf_base64": pdf_b64,
            "letter_text": letter_body,
            "filename": f"tony_{document_type.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}


async def tony_generate_custom_pdf(
    title: str,
    content: str,
    recipient_name: str = "",
    recipient_address: str = ""
) -> Dict:
    """Generate a PDF from provided content — no AI generation, just formatting."""
    try:
        pdf_bytes = _create_pdf(
            title=title,
            body_text=content,
            recipient_name=recipient_name,
            recipient_address=recipient_address
        )
        pdf_b64 = base64.b64encode(pdf_bytes).decode()
        return {
            "ok": True,
            "pdf_base64": pdf_b64,
            "filename": f"tony_{title.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
