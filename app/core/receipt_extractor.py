"""
Receipt + bill extraction.

Given a photo of a receipt, invoice, or bill:
  - Extract merchant, date, total, items (if visible)
  - Categorise the spend (groceries, petrol, utilities, transport, etc.)
  - Store structured for expense tracking + insights

Builds on existing vision. Output is structured — goes into tony_expenses table
for queryable spending analysis over time.
"""
import os
import json
import base64
import httpx
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_expense_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_expenses (
                id SERIAL PRIMARY KEY,
                merchant TEXT,
                purchase_date DATE,
                total NUMERIC(10, 2),
                currency TEXT DEFAULT 'GBP',
                category TEXT,
                items JSONB,
                notes TEXT,
                source TEXT DEFAULT 'receipt_photo',
                image_hash TEXT UNIQUE,
                extracted_at TIMESTAMP DEFAULT NOW(),
                verified BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_expenses_date
            ON tony_expenses(purchase_date DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_expenses_category
            ON tony_expenses(category, purchase_date DESC)
        """)
        cur.close()
        conn.close()
        print("[EXPENSES] Tables initialised")
    except Exception as e:
        print(f"[EXPENSES] Init failed: {e}")


EXTRACTION_PROMPT = """Extract structured data from this receipt/bill/invoice image.

Return STRICT JSON with this schema:
{
  "merchant": "store or provider name",
  "purchase_date": "YYYY-MM-DD (best guess if ambiguous, today if unclear)",
  "total": 00.00,
  "currency": "GBP" | "USD" | "EUR",
  "category": "groceries" | "petrol" | "utilities" | "transport" | "eating_out" |
              "healthcare" | "kids" | "household" | "clothing" | "subscription" |
              "bills" | "other",
  "items": [
    {"name": "item name", "quantity": 1, "price": 0.00}
  ],
  "confidence": 0.0-1.0,
  "notes": "anything unusual or worth flagging"
}

Rules:
- Match UK retailer names carefully (Tesco, Sainsbury's, Aldi, Lidl, M&S, etc.)
- For utility bills, merchant = provider, items = [main service + VAT]
- If it's not actually a receipt/bill, return {"error": "not a receipt", "what_it_is": "description"}
- Round amounts to 2 decimal places
- If date is hard to read, best-guess from YYYY-MM-DD format, mark confidence lower

Respond with JSON only:"""


async def extract_from_image(image_base64: str) -> Dict:
    """Run Gemini vision to extract structured receipt data."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"error": "GEMINI_API_KEY not configured"}

    try:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{
                        "role": "user",
                        "parts": [
                            {"text": EXTRACTION_PROMPT},
                            {"inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64,
                            }}
                        ]
                    }],
                    "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.1}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first < 0 or last < 0:
            return {"error": "Could not parse Gemini response"}

        data = json.loads(cleaned[first:last+1])
        return data
    except Exception as e:
        return {"error": f"Extraction failed: {e}"}


def _image_hash(image_base64: str) -> str:
    """Stable hash for dedup — don't save the same receipt twice."""
    import hashlib
    return hashlib.sha256(image_base64[:10000].encode()).hexdigest()[:32]


def save_expense(data: Dict, image_base64: str) -> Optional[int]:
    """Persist extracted receipt to DB. Returns new row id or None."""
    if "error" in data:
        return None
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        h = _image_hash(image_base64)
        cur.execute("""
            INSERT INTO tony_expenses
                (merchant, purchase_date, total, currency, category,
                 items, notes, image_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (image_hash) DO UPDATE SET
                merchant = EXCLUDED.merchant,
                total = EXCLUDED.total,
                category = EXCLUDED.category
            RETURNING id
        """, (
            (data.get("merchant") or "")[:200],
            data.get("purchase_date") or datetime.utcnow().date(),
            float(data.get("total", 0)),
            (data.get("currency") or "GBP")[:4],
            (data.get("category") or "other")[:30],
            json.dumps(data.get("items", [])),
            (data.get("notes") or "")[:500],
            h,
        ))
        new_id = cur.fetchone()[0]
        cur.close()
        conn.close()
        return new_id
    except Exception as e:
        print(f"[EXPENSES] Save failed: {e}")
        return None


def get_expense_summary(days: int = 30) -> Dict:
    """Spending summary over a period — total, by category, by merchant."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*), COALESCE(SUM(total), 0)
            FROM tony_expenses
            WHERE purchase_date > NOW() - INTERVAL '{int(days)} days'
        """)
        count, total = cur.fetchone()

        cur.execute(f"""
            SELECT category, COUNT(*), COALESCE(SUM(total), 0)
            FROM tony_expenses
            WHERE purchase_date > NOW() - INTERVAL '{int(days)} days'
            GROUP BY category
            ORDER BY SUM(total) DESC
        """)
        by_category = [
            {"category": r[0], "count": r[1], "total": float(r[2])}
            for r in cur.fetchall()
        ]

        cur.execute(f"""
            SELECT merchant, COUNT(*), COALESCE(SUM(total), 0)
            FROM tony_expenses
            WHERE purchase_date > NOW() - INTERVAL '{int(days)} days'
            GROUP BY merchant
            ORDER BY SUM(total) DESC LIMIT 10
        """)
        top_merchants = [
            {"merchant": r[0], "count": r[1], "total": float(r[2])}
            for r in cur.fetchall()
        ]
        cur.close()
        conn.close()

        return {
            "days": days,
            "count": count,
            "total": float(total),
            "by_category": by_category,
            "top_merchants": top_merchants,
        }
    except Exception as e:
        return {"error": str(e)}


def list_recent_expenses(limit: int = 20) -> List[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, merchant, purchase_date, total, currency, category, items, verified
            FROM tony_expenses
            ORDER BY purchase_date DESC, extracted_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "merchant": r[1], "date": str(r[2]),
             "total": float(r[3] or 0), "currency": r[4],
             "category": r[5], "items": r[6], "verified": r[7]}
            for r in rows
        ]
    except Exception:
        return []
