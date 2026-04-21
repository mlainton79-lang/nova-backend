"""
Fabrication detector.

Runs after each Tony response. Looks for specific factual claims that weren't
in the user message or stored facts. Doesn't rewrite Tony's output (too risky),
but LOGS suspected fabrications so patterns become visible in the eval data.

If patterns are strong, the self-improvement loop can propose prompt fixes.
"""
import os
import re
import json
import psycopg2
from typing import List, Dict, Set


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_fabrication_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_suspected_fabrications (
                id SERIAL PRIMARY KEY,
                user_message TEXT,
                assistant_reply TEXT,
                suspected_claims JSONB,
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed_at TIMESTAMP,
                verdict TEXT
            )
        """)
        cur.close()
        conn.close()
        print("[FABRICATION] Tables initialised")
    except Exception as e:
        print(f"[FABRICATION] Init failed: {e}")


# Patterns that suggest Tony is making specific factual claims
# about things Matthew hasn't mentioned
SUSPICIOUS_PATTERNS = [
    # Brand names in pricing/shopping context
    (r'\b(Zara|H&M|Next|Primark|Asos|Boohoo|Nike|Adidas|Gucci|Prada|Burberry|All Saints|COS|Arket|Whistles)\b',
     "brand_name"),
    # Specific numeric claims
    (r'£\s?\d+\.\d{2}(?!\s?(?:each|per))',  "specific_price"),
    (r'\bRRP\s?£\s?\d+', "specific_rrp"),
    # Specific sizes
    (r'\bsize\s+\d+\b', "specific_size"),
    # Specific conditions
    (r'\b(worn\s+(?:once|twice|three\s+times|\d+\s+times))\b', "specific_wear"),
    # Naming specific people Matthew didn't mention
    # (we can only flag these if we know who he mentioned — skip for now)
]


def scan_for_suspicious_claims(user_message: str, reply: str) -> List[Dict]:
    """Find specific factual claims in reply that aren't in user message."""
    user_lower = user_message.lower()
    claims = []

    for pattern, tag in SUSPICIOUS_PATTERNS:
        for match in re.finditer(pattern, reply, re.IGNORECASE):
            text = match.group(0)
            # Skip if the user said this
            if text.lower() in user_lower:
                continue
            # Skip if a simple fragment of it is in user message
            if tag == "brand_name" and text.lower() in user_lower:
                continue
            claims.append({
                "tag": tag,
                "text": text,
                "position": match.start(),
                "in_user_msg": False,
            })

    return claims


def check_against_fact_store(claims: List[Dict]) -> List[Dict]:
    """For each claim, check if it appears in the fact store."""
    if not claims:
        return []
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Get all known facts about Matthew
        cur.execute("""
            SELECT object FROM tony_facts
            WHERE superseded_by IS NULL AND confidence > 0.5
        """)
        all_facts = " ".join(r[0] for r in cur.fetchall()).lower()
        cur.close()
        conn.close()

        for c in claims:
            c["in_fact_store"] = c["text"].lower() in all_facts
    except Exception:
        for c in claims:
            c["in_fact_store"] = False
    return claims


async def check_and_log(user_message: str, reply: str) -> Dict:
    """Main entry. Non-blocking post-response check."""
    claims = scan_for_suspicious_claims(user_message, reply)
    claims = check_against_fact_store(claims)

    unverified = [c for c in claims if not c.get("in_fact_store")]

    if not unverified:
        return {"suspected": 0}

    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_suspected_fabrications
                (user_message, assistant_reply, suspected_claims)
            VALUES (%s, %s, %s)
        """, (user_message[:1000], reply[:2000], json.dumps(unverified)))
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[FABRICATION] Log failed: {e}")

    print(f"[FABRICATION] {len(unverified)} unverified claims in reply: "
          f"{[c['text'] for c in unverified][:3]}")
    return {"suspected": len(unverified), "claims": unverified}


def list_recent_suspicions(limit: int = 20) -> List[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_message, assistant_reply, suspected_claims, created_at
            FROM tony_suspected_fabrications
            WHERE verdict IS NULL
            ORDER BY created_at DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "user_message": r[1][:200],
             "reply": r[2][:300], "claims": r[3],
             "created_at": str(r[4])}
            for r in rows
        ]
    except Exception:
        return []


def mark_verdict(fabrication_id: int, verdict: str):
    """verdict: 'confirmed_fabrication' | 'actually_true' | 'inconclusive'"""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_suspected_fabrications
            SET verdict = %s, reviewed_at = NOW() WHERE id = %s
        """, (verdict, fabrication_id))
        cur.close()
        conn.close()
        return True
    except Exception:
        return False
