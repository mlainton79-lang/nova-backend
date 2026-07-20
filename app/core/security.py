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
    Unset DIAG_TOKEN = feature off (DEV_TOKEN still works). Never attach
    this to any endpoint that mutates state, sends, posts, or triggers.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token == DEV_TOKEN:
        return
    if DIAG_TOKEN and token == DIAG_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Invalid token")
