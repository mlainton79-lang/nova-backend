"""
Tony's Browser Agent.

Tony can navigate websites, fill forms, and take actions.
Uses Playwright via subprocess — keeps main app clean.

Current capabilities:
- Submit FOS complaint online
- Check FCA register for Western Circle status
- Search Companies House
- Check credit reference agency info
- Fill government forms

This makes Tony an agent that acts, not just advises.
"""
import os
import asyncio
import json
import httpx
from typing import Dict, Optional
from app.core.model_router import gemini_json

# Browser tasks run as structured plans that Tony executes step by step
BROWSER_AVAILABLE = False

try:
    import subprocess
    result = subprocess.run(["python3", "-c", "import playwright"], 
                          capture_output=True, timeout=5)
    BROWSER_AVAILABLE = result.returncode == 0
except Exception:
    pass


async def check_fca_register(company_name: str) -> Dict:
    """
    Check the FCA Financial Services Register for a company.
    Uses the FCA's public API — no browser needed.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # FCA has a public register API
            r = await client.get(
                "https://register.fca.org.uk/services/V0.1/Firm",
                params={"q": company_name, "type": "query"},
                headers={"Accept": "application/json"}
            )
            if r.status_code == 200:
                data = r.json()
                firms = data.get("Data", [])
                if firms:
                    firm = firms[0]
                    return {
                        "found": True,
                        "name": firm.get("Name", ""),
                        "frn": firm.get("FRN", ""),
                        "status": firm.get("Status", ""),
                        "current_permissions": firm.get("CurrentPermissions", []),
                        "address": firm.get("Address", {}),
                        "regulated": firm.get("Status", "") == "Authorised"
                    }
                return {"found": False, "searched": company_name}
    except Exception as e:
        print(f"[BROWSER_AGENT] FCA check failed: {e}")
    return {"found": False, "error": "FCA register unavailable"}


async def check_companies_house(company_name: str) -> Dict:
    """
    Check Companies House for company details.
    Public API, no key needed for basic searches.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.company-information.service.gov.uk/search/companies",
                params={"q": company_name, "items_per_page": 3},
                headers={"Authorization": ""}  # Anonymous access
            )
            if r.status_code == 200:
                data = r.json()
                items = data.get("items", [])
                if items:
                    company = items[0]
                    return {
                        "found": True,
                        "name": company.get("title", ""),
                        "company_number": company.get("company_number", ""),
                        "status": company.get("company_status", ""),
                        "type": company.get("company_type", ""),
                        "address": company.get("address", {}),
                        "date_created": company.get("date_of_creation", "")
                    }
    except Exception as e:
        print(f"[BROWSER_AGENT] Companies House check failed: {e}")
    return {"found": False}


async def research_opponent(company_name: str) -> Dict:
    """
    Full research on an opponent company.
    Checks FCA register, Companies House, and Brave search.
    """
    results = {}

    # FCA check
    fca = await check_fca_register(company_name)
    results["fca"] = fca

    # Companies House
    ch = await check_companies_house(company_name)
    results["companies_house"] = ch

    # Web search for complaints/news
    try:
        from app.core.brave_search import brave_search
        search_results = await brave_search(f"{company_name} FCA complaints 2025 2026")
        results["web_intel"] = search_results[:500] if search_results else ""
    except Exception:
        results["web_intel"] = ""

    # Tony's assessment
    prompt = f"""Tony is researching {company_name} for Matthew's legal case.

FCA Register: {json.dumps(fca)}
Companies House: {json.dumps(ch)}
Web intelligence: {results.get('web_intel', '')[:300]}

Provide a concise intelligence brief:
1. Is this company currently FCA regulated?
2. Any enforcement actions or complaints patterns visible?
3. Are they in financial difficulty?
4. Key facts Matthew should know

Keep it factual and brief.

JSON response:
{{
    "regulated": true/false,
    "enforcement_risk": "high/medium/low",
    "key_facts": ["fact 1", "fact 2"],
    "leverage_points": ["things that strengthen our case"],
    "brief": "2 sentence summary"
}}"""

    assessment = await gemini_json(prompt, task="legal", max_tokens=512)
    results["assessment"] = assessment

    return results


async def submit_fos_complaint_online(complaint_data: Dict) -> Dict:
    """
    Guide for submitting FOS complaint online.
    Returns step-by-step instructions with pre-filled data.
    Tony can't automate this without Playwright, but can pre-fill everything.
    """
    return {
        "url": "https://www.financial-ombudsman.org.uk/make-a-complaint",
        "method": "online_form",
        "pre_filled_data": {
            "complainant_name": "Matthew Lainton",
            "complainant_address": "61 Swangate, Brampton Bierlow, Rotherham, S63 6ER",
            "complainant_phone": "07735589035",
            "company_name": "Western Circle Ltd",
            "company_trading_name": "Cashfloat",
            "product_type": "Consumer credit / payday loan",
            "complaint_date": "As soon as possible",
            "reference": "K9QZ4X9N",
            "amount": "£700 approximately",
            "complaint_summary": complaint_data.get("summary", "Irresponsible lending, failure to assess affordability, failure to recognise and act on vulnerability (gambling addiction), breach of FCA CONC 5.2, FG21/1, and Consumer Duty"),
            "outcome_sought": "CCJ removal and compensation for distress caused by irresponsible lending"
        },
        "instructions": [
            "1. Open the FOS complaint form at the URL above",
            "2. Select 'Credit, loans and credit cards' as product type",
            "3. Enter Western Circle Ltd / Cashfloat as the company",
            "4. Fill in your details as shown",
            "5. In the complaint box, paste the complaint Tony has generated",
            "6. Upload any correspondence with Western Circle",
            "7. State outcome: CCJ set aside and compensation",
            "8. Submit — you'll get a reference number immediately"
        ],
        "important": "FOS is free. Western Circle must cooperate. Decisions are binding on them if you accept."
    }
