"""
Tony's Correspondence Management Engine.

Tony doesn't just draft letters — he manages entire correspondence threads.

For the Western Circle case:
1. Tony reads all emails from Western Circle
2. Understands their position and arguments
3. Knows the legal grounds (CONC rules, FCA, FOS)
4. Drafts targeted responses to their specific points
5. Tracks the full correspondence timeline
6. Identifies when to escalate to FOS
7. Prepares the actual FOS complaint when ready

This is Tony acting as Matthew's legal correspondent.
Not a lawyer — but armed with the right knowledge and context.
"""
import os
import json
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json

BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_correspondence_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_correspondence (
                id SERIAL PRIMARY KEY,
                case_name TEXT NOT NULL,
                thread_id TEXT,
                direction TEXT NOT NULL, -- 'inbound' or 'outbound'
                from_party TEXT,
                to_party TEXT,
                subject TEXT,
                body TEXT,
                date_sent TIMESTAMP,
                status TEXT DEFAULT 'active', -- active, responded, escalated, resolved
                key_points TEXT[], -- Array of key points/arguments made
                tony_assessment TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_cases (
                id SERIAL PRIMARY KEY,
                case_name TEXT NOT NULL UNIQUE,
                case_type TEXT, -- ccj, complaint, dispute, claim
                opponent TEXT,
                our_position TEXT,
                their_position TEXT,
                legal_grounds TEXT[],
                timeline TEXT,
                next_action TEXT,
                next_action_deadline TIMESTAMP,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Seed Western Circle case
        cur.execute("""
            INSERT INTO tony_cases (
                case_name, case_type, opponent, our_position,
                their_position, legal_grounds, next_action, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (case_name) DO NOTHING
        """, (
            "Western Circle CCJ",
            "ccj",
            "Western Circle Ltd (Cashfloat)",
            "CCJ should be set aside on grounds of irresponsible lending. Western Circle failed affordability checks (CONC 5.2), failed vulnerability obligations (FG21/1), and breached Consumer Duty. Matthew had gambling addiction at time of lending which constitutes vulnerability under FCA rules.",
            "Affordability checks were sufficient. Debt is valid.",
            ["CONC 5.2 - affordability assessment", "FG21/1 - vulnerable customer guidance", "CONC 7.3 - forbearance", "Consumer Duty PS22/9", "FOS jurisdiction over regulated credit"],
            "File FOS complaint or apply to court to set aside CCJ (Form N244)",
            "active"
        ))
        conn.commit()
        cur.close()
        conn.close()
        print("[CORRESPONDENCE] Tables initialised")
    except Exception as e:
        print(f"[CORRESPONDENCE] Init failed: {e}")


async def analyse_incoming_letter(
    case_name: str,
    letter_text: str,
    from_party: str
) -> Dict:
    """
    Tony reads an incoming letter and extracts key points,
    assesses their position, and identifies how to respond.
    """
    case = await get_case(case_name)
    case_context = ""
    if case:
        case_context = f"""
Case: {case.get('case_name', '')}
Our position: {case.get('our_position', '')}
Their previous position: {case.get('their_position', '')}
Legal grounds we're relying on: {', '.join(case.get('legal_grounds', []))}"""

    prompt = f"""Tony is acting as Matthew Lainton's personal legal correspondent.

{case_context}

New letter received from {from_party}:
---
{letter_text[:3000]}
---

Analyse this letter and identify:
1. What are they claiming/arguing?
2. Have they acknowledged any of our grounds?
3. Are there any admissions or weaknesses in their position?
4. What legal points do they raise?
5. What should our response focus on?
6. Has anything changed that affects our strategy?
7. Should we respond directly or escalate to FOS now?

Be specific. Reference actual legal rules where relevant.

Respond in JSON:
{{
    "their_key_points": ["what they argued"],
    "admissions": ["anything they admitted or conceded"],
    "weaknesses": ["weaknesses in their position"],
    "our_response_strategy": "how we should respond",
    "escalate_to_fos": true/false,
    "escalation_reason": "why now is right for FOS (or null)",
    "urgency": "urgent/normal/low",
    "tony_assessment": "Tony's overall assessment in 2 sentences"
}}"""

    return await gemini_json(prompt, task="legal", max_tokens=1024) or {}


async def draft_response_letter(
    case_name: str,
    incoming_analysis: Dict,
    specific_instruction: str = ""
) -> str:
    """Draft a response letter based on Tony's analysis."""
    case = await get_case(case_name)
    case_context = ""
    if case:
        case_context = f"Case: {case.get('case_name', '')}\nOur position: {case.get('our_position', '')}"

    prompt = f"""Tony is drafting a formal letter on behalf of Matthew Lainton.

{case_context}

Their key points: {json.dumps(incoming_analysis.get('their_key_points', []))}
Their weaknesses: {json.dumps(incoming_analysis.get('weaknesses', []))}
Our response strategy: {incoming_analysis.get('our_response_strategy', '')}
{f'Specific instruction: {specific_instruction}' if specific_instruction else ''}

Matthew's details:
- Name: Matthew Lainton
- Address: 61 Swangate, Brampton Bierlow, Rotherham, S63 6ER
- Phone: 07735589035
- NI: JK985746C
- Reference: K9QZ4X9N

Write a complete, formal letter that:
- Directly addresses each of their points
- Reinforces our legal grounds (CONC 5.2, FG21/1, Consumer Duty)
- Is firm, professional, and factually accurate
- References specific FCA rules by number where relevant
- Ends with a clear statement of what we require from them
- British English, formal register

Write the complete letter now. Do not truncate."""

    return await gemini(prompt, task="legal", max_tokens=4096, temperature=0.2) or ""


async def get_case(case_name: str) -> Optional[Dict]:
    """Get case details."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT case_name, case_type, opponent, our_position,
                   their_position, legal_grounds, next_action, status
            FROM tony_cases WHERE case_name = %s
        """, (case_name,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "case_name": row[0], "case_type": row[1], "opponent": row[2],
                "our_position": row[3], "their_position": row[4],
                "legal_grounds": row[5] or [], "next_action": row[6], "status": row[7]
            }
    except Exception as e:
        print(f"[CORRESPONDENCE] Get case failed: {e}")
    return None


async def prepare_fos_complaint() -> Dict:
    """
    Tony prepares a complete FOS complaint for the Western Circle case.
    Pulls all correspondence, builds the chronology, writes the complaint.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT direction, from_party, subject, body, date_sent
            FROM tony_correspondence
            WHERE case_name = 'Western Circle CCJ'
            ORDER BY date_sent ASC
        """)
        correspondence = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        correspondence = []

    corr_text = ""
    if correspondence:
        corr_text = "\n\n".join(
            f"[{r[0].upper()}] {r[2]} ({r[4]})\n{r[3][:300]}"
            for r in correspondence
        )

    prompt = f"""Tony is preparing a formal FOS (Financial Ombudsman Service) complaint on behalf of Matthew Lainton against Western Circle Ltd (Cashfloat).

Matthew's details:
- Full name: Matthew Lainton
- Address: 61 Swangate, Brampton Bierlow, Rotherham, S63 6ER
- Phone: 07735589035
- Reference: K9QZ4X9N (CCJ reference)
- Approximate amount: £700

Grounds for complaint:
1. Irresponsible lending — Western Circle failed adequate affordability assessment (CONC 5.2)
2. Vulnerability — Matthew had a gambling addiction at the time of lending, constituting vulnerability under FG21/1
3. Western Circle acknowledged vulnerability but maintained checks were sufficient — this acknowledgment is an admission
4. Failure to apply forbearance and due consideration (CONC 7.3)
5. Consumer Duty breach (PS22/9) — failure to act in consumer's best interests
6. The resulting CCJ is direct evidence of lending failure

Correspondence history:
{corr_text if corr_text else 'No correspondence on file yet — complaint based on known facts'}

Write a complete, detailed FOS complaint that:
- Opens with clear statement of complaint
- Gives chronological account of events
- References each FCA rule violation specifically
- Explains what outcome we're seeking (CCJ removal, compensation consideration)
- Is written in first person from Matthew's perspective
- Is professional, factual, and compelling
- Complete — do not truncate

Write the full complaint now:"""

    complaint_text = await gemini(prompt, task="legal", max_tokens=8192, temperature=0.2)

    # Generate PDF
    if complaint_text:
        from app.core.document_generator import tony_generate_custom_pdf
        pdf = await tony_generate_custom_pdf(
            title="FOS Complaint — Western Circle Ltd (Cashfloat)",
            content=complaint_text,
            recipient_name="Financial Ombudsman Service",
            recipient_address="Exchange Tower\nHarbour Exchange\nLondon\nE14 9SR"
        )
        return {
            "ok": True,
            "complaint_text": complaint_text,
            "pdf": pdf,
            "next_step": "Submit at financial-ombudsman.org.uk/make-a-complaint or post to: Financial Ombudsman Service, Exchange Tower, London, E14 9SR"
        }

    return {"ok": False, "error": "Failed to generate complaint"}
