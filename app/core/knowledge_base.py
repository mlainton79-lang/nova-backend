"""
Tony's Knowledge Base.

Static knowledge Tony always has access to.
Seeded with domains most relevant to Matthew's life:
- UK consumer credit law (generic)
- FOS complaint process
- General court / debt dispute processes
- Employment rights (care work)
- Vinted/eBay selling rules
- Universal Credit rules
- Rotherham local info

This is different from memory — it's expert knowledge
Tony uses to answer questions accurately.
"""
import os
import psycopg2
from typing import Optional

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


KNOWLEDGE_ENTRIES = [
    # UK Consumer Credit Law
    ("consumer_credit_law", "CONC 5.2 Affordability", 
     "Under FCA CONC 5.2, lenders must carry out a reasonable creditworthiness assessment before lending. They must consider the consumer's ability to make repayments. Failure to do so is grounds for complaint and potentially makes the debt unenforceable."),
    
    ("consumer_credit_law", "FG21/1 Vulnerability",
     "FCA Guidance FG21/1 requires firms to identify and treat vulnerable customers fairly. Gambling addiction is explicitly recognised as a vulnerability. If a borrower had a gambling addiction at the time of lending and the lender failed to identify and accommodate this, it constitutes a serious breach."),
    
    ("consumer_credit_law", "Consumer Duty PS22/9",
     "The FCA's Consumer Duty (PS22/9) requires firms to act to deliver good outcomes for retail customers. It applies from July 2023. For ongoing credit agreements pre-dating the Duty, firms still have obligations around fair treatment and must not cause foreseeable harm."),
    
    ("consumer_credit_law", "CONC 7.3 Forbearance",
     "Under CONC 7.3, lenders must show forbearance to borrowers in financial difficulty. This includes considering payment plans, not adding excessive charges, and treating customers with dignity. Failure to show forbearance strengthens a complaint."),
    
    
    # eBay/Vinted
    ("selling_platforms", "Vinted Rules",
     "Vinted charges no seller fees in UK. Buyer pays a buyer protection fee. Items must be second-hand. Prohibited: new items with tags (unless disclosed), counterfeit goods. Best practices: good photos, accurate measurements, honest condition description, respond to messages quickly."),
    
    ("selling_platforms", "eBay Fees",
     "eBay charges approximately 12.9% final value fee for most categories (capped at £1,000). PayPal fees additional ~3.4%. List up to 1,000 items free/month. Best practice: list Thursday-Sunday evenings for maximum visibility. Consider using 'sold' filter to research pricing."),
    
    # Employment
    ("employment_rights", "Care Work Rights",
     "Care workers in UK are entitled to: National Minimum Wage (£11.44/hr 2024-25 for over 21s), paid holiday (5.6 weeks per year), sick pay (SSP minimum), rest breaks (20 mins if shift over 6 hours), sleep-in payments must meet NMW when awake and required to work."),
    
    ("employment_rights", "CQC Outstanding",
     "A CQC Outstanding rating is the highest possible. It means the care home exceeded all standards. This is relevant for job security and quality of employment environment. Outstanding homes tend to have better management and employment practices."),
]


def init_knowledge_base():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_knowledge (
                id SERIAL PRIMARY KEY,
                domain TEXT NOT NULL,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(domain, topic)
            )
        """)
        for domain, topic, content in KNOWLEDGE_ENTRIES:
            cur.execute("""
                INSERT INTO tony_knowledge (domain, topic, content)
                VALUES (%s, %s, %s)
                ON CONFLICT (domain, topic) DO UPDATE SET content = EXCLUDED.content
            """, (domain, topic, content))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[KNOWLEDGE] Seeded {len(KNOWLEDGE_ENTRIES)} entries")
    except Exception as e:
        print(f"[KNOWLEDGE] Init failed: {e}")


def get_relevant_knowledge(query: str) -> str:
    """Get knowledge relevant to the query."""
    query_lower = query.lower()
    
    domain_keywords = {
        "consumer_credit_law": ["conc", "affordability", "fca", "lending", "credit", "irresponsible", "vulnerability"],
        "selling_platforms": ["vinted", "ebay", "selling", "listing", "fees", "platform"],
        "employment_rights": ["employment", "rights", "wage", "shift", "work", "care home", "cqc"],
    }
    
    relevant_domains = set()
    for domain, keywords in domain_keywords.items():
        if any(k in query_lower for k in keywords):
            relevant_domains.add(domain)
    
    if not relevant_domains:
        return ""
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT topic, content FROM tony_knowledge
            WHERE domain = ANY(%s)
            ORDER BY domain, topic
            LIMIT 4
        """, (list(relevant_domains),))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        if not rows:
            return ""
        
        lines = ["[TONY'S KNOWLEDGE BASE]:"]
        for topic, content in rows:
            lines.append(f"\n{topic}: {content}")
        
        return "\n".join(lines)
    except Exception:
        return ""
