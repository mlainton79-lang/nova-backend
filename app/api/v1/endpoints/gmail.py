import os
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from app.core.security import verify_token
from app.core.gmail_service import (
    get_auth_url, exchange_code, get_user_email, save_account,
    get_all_accounts, list_emails, get_email_body, send_email,
    trash_email, delete_email, search_all_accounts, get_morning_summary,
    init_gmail_tables
)

router = APIRouter()

def setup_gmail():
    init_gmail_tables()

@router.get("/gmail/auth/init")
async def gmail_auth_init(_=Depends(verify_token)):
    url = get_auth_url()
    return {"auth_url": url}

@router.get("/gmail/auth/callback")
async def gmail_auth_callback(code: str = None, error: str = None, state: str = None):
    if error or not code:
        return HTMLResponse(f"""<html><body style="font-family:sans-serif;padding:40px;background:#1a1225;color:#fff;">
        <h2>❌ Authentication failed</h2><p>{error or "No code received"}</p>
        <p>Close this and try again in Nova.</p></body></html>""")
    try:
        tokens = await exchange_code(code)
        access_token = tokens["access_token"]
        refresh_tok = tokens.get("refresh_token", "")
        expires_in = tokens.get("expires_in", 3600)
        email = await get_user_email(access_token)
        save_account(email, access_token, refresh_tok, expires_in)
        return HTMLResponse(f"""<html><body style="font-family:sans-serif;padding:40px;background:#1a1225;color:#fff;">
        <h2>✅ {email} connected to Tony</h2>
        <p>Tony now has access to this Gmail account.</p>
        <p>You can close this page and return to Nova.</p>
        <p style="margin-top:30px;color:#9B8FBF;">To add another account, ask Tony to connect another Gmail.</p>
        </body></html>""")
    except Exception as e:
        return HTMLResponse(f"""<html><body style="font-family:sans-serif;padding:40px;background:#1a1225;color:#fff;">
        <h2>❌ Error</h2><p>{str(e)}</p></body></html>""")

@router.get("/gmail/accounts")
async def gmail_accounts(_=Depends(verify_token)):
    accounts = get_all_accounts()
    return {"accounts": accounts, "count": len(accounts)}

@router.get("/gmail/emails")
async def gmail_list(account: str = None, query: str = "", max_results: int = 20, label: str = "INBOX", _=Depends(verify_token)):
    if account:
        emails = await list_emails(account, query=query, max_results=max_results, label=label)
    else:
        emails = await search_all_accounts(query=query or "is:unread", max_per_account=max_results)
    return {"emails": emails, "count": len(emails)}

@router.get("/gmail/email/{message_id}")
async def gmail_get(message_id: str, account: str, _=Depends(verify_token)):
    return await get_email_body(account, message_id)

@router.get("/gmail/search")
async def gmail_search(query: str, max_per_account: int = 10, _=Depends(verify_token)):
    results = await search_all_accounts(query, max_per_account)
    return {"results": results, "count": len(results)}

@router.post("/gmail/send")
async def gmail_send(account: str, to: str, subject: str, body: str, reply_to_id: str = None, _=Depends(verify_token)):
    ok = await send_email(account, to, subject, body, reply_to_id)
    return {"ok": ok}

@router.post("/gmail/trash/{message_id}")
async def gmail_trash(message_id: str, account: str, _=Depends(verify_token)):
    ok = await trash_email(account, message_id)
    return {"ok": ok}

@router.delete("/gmail/delete/{message_id}")
async def gmail_delete(message_id: str, account: str, _=Depends(verify_token)):
    ok = await delete_email(account, message_id)
    return {"ok": ok}

@router.get("/gmail/morning")
async def gmail_morning(_=Depends(verify_token)):
    summary = await get_morning_summary()
    return {"summary": summary}
