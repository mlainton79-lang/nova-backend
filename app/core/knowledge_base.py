"""
Tony's Knowledge Base.

Structured, searchable knowledge about topics relevant to Matthew.
Different from memory (facts about Matthew's life) and world model
(Matthew's current situation) — this is domain knowledge Tony
maintains and updates about specific subjects.

Current knowledge domains:
- UK consumer credit law (FCA CONC rules, CCJ process)
- UK employment law (care home worker rights)
- UK financial regulations (Consumer Duty, FOS process)
- Vinted/eBay selling (pricing, listings, fees)
- Care home regulations (CQC standards)

Tony updates knowledge when he learns something new.
Knowledge is versioned — Tony knows what changed and when.
"""
import os
import json
import httpx
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_knowledge_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_knowledge (
                id SERIAL PRIMARY KEY,
                domain TEXT NOT NULL,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT,
                confidence FLOAT DEFAULT 0.8,
                version INTEGER DEFAULT 1,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(domain, topic)
            )
        """)

        # Seed with core knowledge Matthew needs
        knowledge = [
            ("uk_consumer_credit", "ccj_set_aside", """
CCJ Set Aside Process (UK):
- Apply using Form N244 at the court that issued the judgment
- Fee: £303 (or free if on certain benefits)
- Grounds: did not receive claim form, or have a real prospect of defending
- Must apply promptly — no strict time limit but delay weakens case
- If CCJ less than 1 month old: can apply to have it 'cancelled' (set aside as of right)
- Evidence needed: statement of truth, grounds for defence, any supporting documents
- On success: CCJ removed from credit file within 28 days
- Western Circle CCJ ref: K9QZ4X9N
            """.strip(), "UK courts guidance", 0.9),

            ("uk_consumer_credit", "fos_complaint_process", """
Financial Ombudsman Service (FOS) Process:
- Free for consumers
- Must complain to firm first, wait 8 weeks for response (or final response letter)
- Then can escalate to FOS within 6 months of firm's final response
- FOS can order: compensation, CCJ removal, loan write-off
- Western Circle must cooperate with FOS investigation
- FOS decisions binding on firm if consumer accepts
- Average decision time: 3-6 months
- Online form: financial-ombudsman.org.uk
- FOS stronger than FCA for individual redress
            """.strip(), "FOS website", 0.9),

            ("uk_consumer_credit", "fca_conc_rules", """
FCA CONC Rules — Key provisions for Matthew's case:
- CONC 5.2: Creditworthiness assessment — lender must assess ability to repay sustainably
- CONC 5.2.1: Must consider income, expenditure, financial commitments
- CONC 7.3: Forbearance — must treat customers in financial difficulty with forbearance
- CONC 7.3.4: Must not pressurise customer
- Consumer Duty (PS22/9, effective July 2023): Act in customer's best interest
- FG21/1: Vulnerable customer guidance — must identify and respond to vulnerability
- Gambling addiction = vulnerability under FCA rules
- If lender knew or should have known about vulnerability: heightened duty of care
            """.strip(), "FCA Handbook", 0.95),

            ("uk_consumer_credit", "irresponsible_lending_grounds", """
Grounds for irresponsible lending claim against Western Circle:
1. Failed adequate affordability assessment (CONC 5.2)
2. Matthew had gambling addiction — constitutes vulnerability (FG21/1)
3. Western Circle acknowledged vulnerability but maintained checks were sufficient
4. This acknowledgment is evidence they knew about the vulnerability
5. Failure to apply forbearance when Matthew was in difficulty (CONC 7.3)
6. Consumer Duty breach — not acting in Matthew's best interest
Key argument: The CCJ itself is evidence of the lending failure — if the loan had
been properly assessed, it would not have been granted and the CCJ would not exist.
            """.strip(), "Legal analysis", 0.85),

            ("vinted_ebay", "selling_basics", """
Vinted selling tips:
- Free to list, Vinted takes 5% + 70p buyer protection fee (paid by buyer)
- Best categories: branded clothing, vintage, designer
- Photos: natural light, flat lay or on body, multiple angles
- Pricing: search sold items on eBay for comparable prices
- Fast sellers: Nike, Adidas, Stone Island, North Face, Ralph Lauren
- Bundle offers increase average sale value
- Active listing (responding quickly) boosts visibility

eBay selling:
- Final value fee: ~12.8% for most categories
- Free listings: 1000/month for most sellers
- Sold price research: search → filter by Sold Items
- PayPal/managed payments — funds held 2-3 days initially
            """.strip(), "Platform guidelines", 0.8),

            ("care_home_regulations", "cqc_standards", """
CQC Outstanding Rating — Sid Bailey Care Home:
- Rated Outstanding (highest rating) as of April 2025
- CQC inspects: Safe, Effective, Caring, Responsive, Well-led
- Outstanding means exemplary in multiple areas
- Night shift workers are critical to maintaining rating
- Matthew works nights — CQC values consistent skilled night cover
- Employer obligations: safe staffing, adequate breaks, training
            """.strip(), "CQC website", 0.85),

            ("uk_employment", "care_worker_rights", """
Care worker employment rights (UK):
- Minimum wage: £11.44/hr (2024 rate, 21+)
- Right to written contract within 2 months
- Working Time Regulations: max 48hr week (can opt out)
- Night worker health assessment rights
- Annual leave: 5.6 weeks minimum
- Sick pay: SSP £116.75/week minimum
- If on zero hours: still entitled to holiday pay, NMW, SSP
- Whistleblowing protection for CQC/quality concerns
            """.strip(), "ACAS / Gov.uk", 0.85),
        ]

        for domain, topic, content, source, confidence in knowledge:
            cur.execute("""
                INSERT INTO tony_knowledge (domain, topic, content, source, confidence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (domain, topic) DO NOTHING
            """, (domain, topic, content, source, confidence))

        conn.commit()
        cur.close()
        conn.close()
        print("[KNOWLEDGE] Tables and seed data initialised")
    except Exception as e:
        print(f"[KNOWLEDGE] Init failed: {e}")


def search_knowledge(query: str, domain: str = None, top_k: int = 3) -> List[Dict]:
    """Search knowledge base by keyword."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        if domain:
            cur.execute("""
                SELECT domain, topic, content, confidence
                FROM tony_knowledge
                WHERE active = TRUE AND domain = %s
                AND (content ILIKE %s OR topic ILIKE %s)
                ORDER BY confidence DESC
                LIMIT %s
            """, (domain, f"%{query}%", f"%{query}%", top_k))
        else:
            cur.execute("""
                SELECT domain, topic, content, confidence
                FROM tony_knowledge
                WHERE active = TRUE
                AND (content ILIKE %s OR topic ILIKE %s)
                ORDER BY confidence DESC
                LIMIT %s
            """, (f"%{query}%", f"%{query}%", top_k))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"domain": r[0], "topic": r[1], "content": r[2], "confidence": r[3]} for r in rows]
    except Exception as e:
        print(f"[KNOWLEDGE] Search failed: {e}")
        return []


def get_relevant_knowledge(message: str) -> str:
    """Get knowledge relevant to the current message for system prompt injection."""
    keywords = {
        "ccj": "ccj",
        "set aside": "set_aside",
        "fos": "fos",
        "ombudsman": "fos",
        "fca": "fca",
        "conc": "conc",
        "irresponsible": "irresponsible",
        "western circle": "irresponsible",
        "cashfloat": "irresponsible",
        "vinted": "vinted",
        "ebay": "vinted",
        "selling": "vinted",
        "cqc": "cqc",
        "care home": "cqc",
        "employment": "employment",
        "rights": "employment",
    }

    msg = message.lower()
    topics_to_fetch = set()
    for keyword, topic in keywords.items():
        if keyword in msg:
            topics_to_fetch.add(topic)

    if not topics_to_fetch:
        return ""

    results = []
    for topic in topics_to_fetch:
        knowledge = search_knowledge(topic, top_k=2)
        results.extend(knowledge)

    if not results:
        return ""

    lines = ["[TONY'S KNOWLEDGE BASE]:"]
    for k in results[:3]:
        lines.append(f"\n{k['topic'].upper().replace('_', ' ')}:\n{k['content'][:400]}")

    return "\n".join(lines)
