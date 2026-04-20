import os
from fastapi import APIRouter, Depends, HTTPException
import httpx
import psycopg2
from pydantic import BaseModel
from app.core.security import verify_token
from datetime import datetime

router = APIRouter()

# Assuming Vinted API credentials and database URL are set as environment variables
VINTED_API_KEY = os.environ.get("VINTED_API_KEY", "")
VINTED_API_SECRET = os.environ.get("VINTED_API_SECRET", "")

@router.get("/post_to_vinted/test")
async def test_post_to_vinted(_=Depends(verify_token)):
    return {"status": "OK"}

class VintedItem(BaseModel):
    title: str
    description: str
    price: float
    # Add other required fields according to Vinted API documentation

@router.post("/post_to_vinted")
async def post_to_vinted(item: VintedItem, _=Depends(verify_token)):
    if not VINTED_API_KEY or not VINTED_API_SECRET:
        raise HTTPException(status_code=500, detail="Vinted API credentials are not set")

    # Generate signing payload
    timestamp = int(datetime.now().timestamp())
    method = "POST"
    signing_payload = f"{timestamp}.{method}"

    # Construct Vinted API request
    url = "https://pro.svc.vinted.com/api/item"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VINTED_API_KEY}",
        "X-Vinted-Signature": signing_payload,
        "X-Vinted-Timestamp": str(timestamp),
    }
    data = item.dict()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Failed to post to Vinted: {e}")