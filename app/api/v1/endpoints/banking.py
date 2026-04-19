"""Open Banking endpoint - TrueLayer integration."""
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from app.core.security import verify_token
from app.core.open_banking import (
    get_auth_url, is_configured, get_recent_transactions,
    get_financial_summary, init_banking_tables, TRUELAYER_CLIENT_ID,
    TRUELAYER_CLIENT_SECRET, TRUELAYER_REDIRECT_URI
)
import httpx, os, psycopg2
from datetime import datetime, timedelta

router = APIRouter()


@router.get("/banking/connect")
async def banking_connect():
    """Redirect to TrueLayer OAuth to connect bank account."""
    if not is_configured():
        return {
            "ok": False,
            "error": "TrueLayer not configured",
            "setup": "Add TRUELAYER_CLIENT_ID and TRUELAYER_CLIENT_SECRET to Railway",
            "register": "https://console.truelayer.com"
        }
    url = get_auth_url()
    return RedirectResponse(url=url)


@router.get("/banking/callback")
async def banking_callback(code: str = None, error: str = None):
    """Handle TrueLayer OAuth callback."""
    if error or not code:
        return {"ok": False, "error": error or "No code received"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://auth.truelayer.com/connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": TRUELAYER_CLIENT_ID,
                    "client_secret": TRUELAYER_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": TRUELAYER_REDIRECT_URI
                }
            )
            if r.status_code == 200:
                data = r.json()
                conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO tony_banking_tokens
                    (access_token, refresh_token, token_expiry)
                    VALUES (%s, %s, %s)
                """, (
                    data["access_token"],
                    data.get("refresh_token", ""),
                    datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
                ))
                conn.commit()
                cur.close()
                conn.close()
                return {"ok": True, "message": "Bank connected. Tony now has read-only access to your transactions."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/banking/status")
async def banking_status(_=Depends(verify_token)):
    return {
        "configured": is_configured(),
        "note": "Register at console.truelayer.com then add TRUELAYER_CLIENT_ID and TRUELAYER_CLIENT_SECRET to Railway"
    }


@router.get("/banking/transactions")
async def get_transactions(days: int = 30, _=Depends(verify_token)):
    transactions = await get_recent_transactions(days)
    return {"transactions": transactions, "count": len(transactions)}


@router.get("/banking/summary")
async def financial_summary(_=Depends(verify_token)):
    summary = await get_financial_summary()
    return {"summary": summary, "configured": is_configured()}
