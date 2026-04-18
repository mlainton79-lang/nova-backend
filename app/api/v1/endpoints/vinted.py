"""
Vinted/eBay listing endpoint.
Photo in → full listing out.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.core.vinted import full_listing_pipeline

router = APIRouter()


class ListingRequest(BaseModel):
    image_base64: str
    image_mime: str = "image/jpeg"
    platform: str = "vinted"
    condition: str = "good"
    user_notes: str = ""


@router.post("/vinted/create-listing")
async def create_listing(req: ListingRequest, _=Depends(verify_token)):
    """
    Full pipeline: photo → item identification → price research → listing draft.
    Send a base64 photo, get back a ready-to-post listing with suggested price.
    """
    result = await full_listing_pipeline(
        image_base64=req.image_base64,
        image_mime=req.image_mime,
        platform=req.platform,
        condition=req.condition,
        user_notes=req.user_notes
    )
    return result


@router.post("/vinted/identify")
async def identify_only(req: ListingRequest, _=Depends(verify_token)):
    """Just identify the item — no listing draft."""
    from app.core.vinted import identify_item
    return await identify_item(req.image_base64, req.image_mime)


@router.post("/vinted/price-check")
async def price_check(item_name: str, _=Depends(verify_token)):
    """Research sold prices for any item by name."""
    from app.core.vinted import research_sold_prices
    return await research_sold_prices(item_name, item_name)
