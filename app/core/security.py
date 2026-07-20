from fastapi import Header, HTTPException
from app.core.config import DEV_TOKEN, DIAG_TOKEN

async def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != DEV_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


async def verify_read_token(authorization: str = Header(...)):
    """Auth for READ-ONLY diagnostic endpoints.

    Accepts DEV_TOKEN (full credential) or DIAG_TOKEN (scoped, read-only).
    DIAG_TOKEN exists so diagnosis never requires handing out the master
    credential: if it leaks, an attacker can read status codes, not act.
    Unset DIAG_TOKEN = feature off (DEV_TOKEN still works).

    Returns the scope ("dev" or "diag"). Handlers attached to this
    dependency MUST branch on it: diag-scoped calls may only perform
    passive reads — no token refresh, no external calls, no DB writes
    (Codex P2, review f1b2f96: refresh_access_token mutates state and
    POSTs to Google, so diag callers must never reach it).
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token == DEV_TOKEN:
        return "dev"
    if DIAG_TOKEN and token == DIAG_TOKEN:
        return "diag"
    raise HTTPException(status_code=401, detail="Invalid token")
