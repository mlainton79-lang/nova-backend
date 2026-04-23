"""
Vinted/eBay listing endpoint.
Photo(s) in → full listing out.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator
from typing import Optional, List
from app.core.security import verify_token
from app.core.vinted import full_listing_pipeline

router = APIRouter()


class ImageItem(BaseModel):
    base64: str
    mime: str = "image/jpeg"


class ListingRequest(BaseModel):
    image_base64: Optional[str] = None
    image_mime: str = "image/jpeg"
    platform: str = "vinted"
    condition: str = "good"
    user_notes: str = ""
    images: Optional[List[ImageItem]] = None

    @model_validator(mode="after")
    def validate_image_input(self) -> "ListingRequest":
        single = bool(self.image_base64)
        multi = self.images is not None and len(self.images) > 0
        if single and multi:
            raise ValueError("Provide either image_base64 or images, not both")
        if not single and not multi:
            raise ValueError("Provide either image_base64 or images")
        if multi and not (1 <= len(self.images) <= 6):
            raise ValueError("images must contain 1-6 items")
        return self


@router.post("/vinted/create-listing")
async def create_listing(req: ListingRequest, _=Depends(verify_token)):
    """
    Full pipeline: photo(s) → item identification → price research → listing draft.
    Accepts either a single base64 image (image_base64 + image_mime) or a list
    of images (images[] with 1-6 items, each {"base64": ..., "mime": ...}).
    """
    images_list = [img.model_dump() for img in req.images] if req.images else None
    result = await full_listing_pipeline(
        image_base64=req.image_base64 or "",
        image_mime=req.image_mime,
        platform=req.platform,
        condition=req.condition,
        user_notes=req.user_notes,
        images=images_list,
    )
    return result


@router.post("/vinted/identify")
async def identify_only(req: ListingRequest, _=Depends(verify_token)):
    """Just identify the item — no listing draft."""
    from app.core.vinted import identify_item
    images_list = [img.model_dump() for img in req.images] if req.images else None
    return await identify_item(
        image_base64=req.image_base64 or "",
        image_mime=req.image_mime,
        images=images_list,
    )


@router.post("/vinted/price-check")
async def price_check(item_name: str, _=Depends(verify_token)):
    """Research sold prices for any item by name."""
    from app.core.vinted import research_sold_prices
    return await research_sold_prices(item_name, item_name)
