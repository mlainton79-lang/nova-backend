from fastapi import Header, HTTPException
from app.core.config import DEV_TOKEN

async def verify_token(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != DEV_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
