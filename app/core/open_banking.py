"""
Tony's Open Banking Integration via TrueLayer.

Tony reads Matthew's real bank transactions with permission.
This gives Tony genuine financial awareness — not guesses.

TrueLayer supports all major UK banks:
Monzo, Starling, HSBC, Barclays, Lloyds, NatWest, Santander, etc.

Free tier: personal use, read-only access.

Setup required (one time):
1. Register at console.truelayer.com (free)
2. Get CLIENT_ID and CLIENT_SECRET
3. Matthew authorises his bank via OAuth
4. Tony gets read-only access to transactions

Tony uses this for:
- Spending awareness ("you've spent £340 on food this month")
- Income tracking ("your last 3 shifts paid on X dates")
- Bill detection ("direct debit for £X due in 3 days")
- Financial health alerts ("balance below £100")
- Western Circle payments tracking
"""
import os
import httpx
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional

TRUELAYER_CLIENT_ID = os.environ.get("TRUELAYER_CLIENT_ID", "")
TRUELAYER_CLIENT_SECRET = os.environ.get("TRUELAYER_CLIENT_SECRET", "")
TRUELAYER_REDIRECT_URI = os.environ.get(
    "TRUELAYER_REDIRECT_URI",
    "https://web-production-be42b.up.railway.app/api/v1/banking/callback"
)

TRUELAYER_AUTH_URL = "https://auth.truelayer.com"
TRUELAYER_API_URL = "https://api.truelayer.com"


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_banking_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_banking_tokens (
                id SERIAL PRIMARY KEY,
                bank_name TEXT,
                access_token TEXT,
                refresh_token TEXT,
                token_expiry TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_transactions (
                id SERIAL PRIMARY KEY,
                transaction_id TEXT UNIQUE,
                amount FLOAT,
                currency TEXT DEFAULT 'GBP',
                description TEXT,
                merchant TEXT,
                category TEXT,
                transaction_date DATE,
                running_balance FLOAT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[BANKING] Tables initialised")
    except Exception as e:
        print(f"[BANKING] Init failed: {e}")


def get_auth_url() -> str:
    """Generate TrueLayer OAuth URL for bank connection."""
    if not TRUELAYER_CLIENT_ID:
        return ""
    import urllib.parse
    params = {
        "response_type": "code",
        "client_id": TRUELAYER_CLIENT_ID,
        "scope": "info accounts balance transactions offline_access",
        "redirect_uri": TRUELAYER_REDIRECT_URI,
        "providers": "uk-ob-all uk-oauth-all",
    }
    return f"{TRUELAYER_AUTH_URL}/?{urllib.parse.urlencode(params)}"


def is_configured() -> bool:
    return bool(TRUELAYER_CLIENT_ID and TRUELAYER_CLIENT_SECRET)


async def get_access_token() -> Optional[str]:
    """Get current access token, refreshing if needed."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT access_token, refresh_token, token_expiry
            FROM tony_banking_tokens
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        access_token, refresh_token, expiry = row

        # Refresh if expiring within 5 minutes
        if expiry and datetime.utcnow() > expiry - timedelta(minutes=5):
            return await refresh_access_token(refresh_token)

        return access_token
    except Exception as e:
        print(f"[BANKING] Token fetch failed: {e}")
        return None


async def refresh_access_token(refresh_token: str) -> Optional[str]:
    """Refresh the TrueLayer access token."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{TRUELAYER_AUTH_URL}/connect/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": TRUELAYER_CLIENT_ID,
                    "client_secret": TRUELAYER_CLIENT_SECRET,
                    "refresh_token": refresh_token
                }
            )
            if r.status_code == 200:
                data = r.json()
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE tony_banking_tokens
                    SET access_token = %s,
                        token_expiry = %s
                    WHERE refresh_token = %s
                """, (
                    data["access_token"],
                    datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600)),
                    refresh_token
                ))
                conn.commit()
                cur.close()
                conn.close()
                return data["access_token"]
    except Exception as e:
        print(f"[BANKING] Token refresh failed: {e}")
    return None


async def get_recent_transactions(days: int = 30) -> List[Dict]:
    """Get recent transactions from all connected accounts."""
    token = await get_access_token()
    if not token:
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get accounts
            r = await client.get(
                f"{TRUELAYER_API_URL}/data/v1/accounts",
                headers={"Authorization": f"Bearer {token}"}
            )
            if r.status_code != 200:
                return []

            accounts = r.json().get("results", [])
            all_transactions = []

            from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

            for account in accounts:
                account_id = account["account_id"]
                r2 = await client.get(
                    f"{TRUELAYER_API_URL}/data/v1/accounts/{account_id}/transactions",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"from": from_date}
                )
                if r2.status_code == 200:
                    txns = r2.json().get("results", [])
                    for t in txns:
                        all_transactions.append({
                            "id": t.get("transaction_id", ""),
                            "amount": t.get("amount", 0),
                            "currency": t.get("currency", "GBP"),
                            "description": t.get("description", ""),
                            "merchant": t.get("merchant_name", ""),
                            "category": t.get("transaction_category", ""),
                            "date": t.get("timestamp", "")[:10]
                        })

            # Store in DB
            if all_transactions:
                conn = get_conn()
                cur = conn.cursor()
                for t in all_transactions:
                    cur.execute("""
                        INSERT INTO tony_transactions
                        (transaction_id, amount, description, merchant, category, transaction_date)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (transaction_id) DO NOTHING
                    """, (t["id"], t["amount"], t["description"][:200],
                          t["merchant"][:100], t["category"], t["date"]))
                conn.commit()
                cur.close()
                conn.close()

            return all_transactions

    except Exception as e:
        print(f"[BANKING] Transaction fetch failed: {e}")
        return []


async def get_financial_summary() -> str:
    """Generate Tony's financial awareness summary for system prompt."""
    if not is_configured():
        return ""

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Recent spending by category
        cur.execute("""
            SELECT category, SUM(ABS(amount)) as total, COUNT(*) as count
            FROM tony_transactions
            WHERE transaction_date > NOW() - INTERVAL '30 days'
            AND amount < 0
            GROUP BY category
            ORDER BY total DESC
            LIMIT 5
        """)
        spending = cur.fetchall()

        # Recent income
        cur.execute("""
            SELECT SUM(amount) as total_income, COUNT(*) as count
            FROM tony_transactions
            WHERE transaction_date > NOW() - INTERVAL '30 days'
            AND amount > 0
        """)
        income = cur.fetchone()

        cur.close()
        conn.close()

        if not spending and not (income and income[0]):
            return ""

        lines = ["[FINANCIAL AWARENESS (last 30 days)]:"]
        if income and income[0]:
            lines.append(f"Income: £{income[0]:.2f} ({income[1]} transactions)")
        for cat, total, count in spending:
            lines.append(f"Spending - {cat or 'Other'}: £{total:.2f} ({count} transactions)")

        return "\n".join(lines)

    except Exception as e:
        print(f"[BANKING] Summary failed: {e}")
        return ""
