"""
Tony's Vinted/eBay Automation.

Matthew photographs an item. Tony:
1. Identifies what it is using vision
2. Searches eBay sold listings for real price data
3. Researches the item's condition factors
4. Drafts an optimised Vinted/eBay listing
5. Suggests the best price based on sold data

This turns a photo into a ready-to-post listing in seconds.
"""
import os
import re
import json
import logging
import httpx
from typing import Dict, List, Optional

from app.core import gemini_client

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


async def identify_item(
    image_base64: str = "",
    image_mime: str = "image/jpeg",
    images: Optional[List[Dict]] = None,
) -> Dict:
    """Use Gemini Vision to identify what the item is.

    Accepts either a single image (image_base64 + image_mime) or a list of
    image dicts with shape {"base64": ..., "mime": ...} via `images`.
    If `images` is non-empty, it takes precedence.
    """
    fallback = {
        "visible_text": [],
        "item_name": "Unknown item",
        "brand": "",
        "category": "",
        "estimated_size": "",
        "condition_visible": "used",
        "key_features": [],
        "color": "",
        "material": "",
        "search_query": "",
        "suggested_uk_resale_price": None,
        "price_reasoning": "",
        "parcel_size": "medium",
        "confidence": "low",
        "needs_manual_verification": True,
        "_fallback": True,
    }
    if not GEMINI_API_KEY:
        log.warning("[VINTED] identify_item: GEMINI_API_KEY not configured, using fallback")
        return fallback

    if images:
        image_items = images
    elif image_base64:
        image_items = [{"base64": image_base64, "mime": image_mime}]
    else:
        log.warning("[VINTED] identify_item called with no images, using fallback")
        return fallback

    prompt = """You are a meticulous visual inspector helping sell an item on Vinted/eBay. Your job is to identify the item accurately. Accuracy beats confidence — if unsure, say so.

STEP 1 — Transcribe visible text.
First, list every piece of text, logo, brand mark, or identifying label visible on the item. Include partial text, trademark symbols, model numbers, and made-up-sounding words. Transcribe exactly what you see — do not interpret, translate, or correct it. Even if a word looks like a typo or an unfamiliar brand (e.g. HUNTR/X, Pop Mart, Ty Beanie), write it verbatim. Put these in "visible_text" as a list of strings.

STEP 2 — Identify from visible evidence only.
Use ONLY the visible text and physical features of the item. Do NOT substitute an unknown brand with a similar-sounding brand you know. If the visible text shows "HUNTR/X", write HUNTR/X in brand or item_name — do not write "LEGO Friends" or any other brand you think it "looks like". If no clear brand text is visible, set brand to "Unknown" and describe the item physically.

Never invent character names, series names, franchise names, or licences. If you cannot see a recognisable licence mark or trademark, do NOT guess which film/TV/music/game/toy line the item belongs to.

STEP 3 — Choose confidence honestly.
confidence defaults to "low". Upgrade only if evidence warrants it:
- "medium" only if you are 80%+ certain of BOTH brand AND product type.
- "high" only if you can see clear, unambiguous brand text AND you have seen this exact product before in training.
- If the item appears to be licensed merchandise (film, TV, music, game, toy line) and you are not 100% sure of the licence: confidence MUST be "low".
- If visible_text contains any word or name you don't confidently recognise: confidence MUST be "low".

STEP 4 — Flag uncertain items for manual review.
Set needs_manual_verification to true if the item might be licensed merchandise, rare, collectible, vintage, or antique AND you are not 100% certain of its identity. This warns the user to verify before listing.

Return JSON only (no prose, no markdown):
{
    "visible_text": ["exact strings visible on the item"],
    "item_name": "specific product name based on visible evidence",
    "brand": "brand name verbatim from visible text, or 'Unknown'",
    "category": "clothing/footwear/electronics/homeware/toys/other",
    "estimated_size": "size if clothing/footwear, or dimensions if other",
    "condition_visible": "what condition does it appear to be in from the photo",
    "key_features": ["notable features that affect value"],
    "color": "primary colour e.g. black, navy, multicoloured",
    "material": "primary material e.g. cotton, leather, polyester",
    "suggested_uk_resale_price": 15,
    "price_reasoning": "one sentence explaining the price, e.g. 'Sky Q remotes typically sell for £8-12 used on eBay UK'",
    "parcel_size": "small",
    "confidence": "low",
    "needs_manual_verification": true,
    "search_query": "best search query to find sold prices on eBay e.g. Nike Air Max 90 size 9"
}

Field guidance:
- suggested_uk_resale_price: realistic UK resale price in GBP as a NUMBER (not a string). Base on item type, brand, condition, and typical Vinted/eBay UK pricing.
- parcel_size: one of "small", "medium", "large". Small = fits in a shoebox. Medium = larger than a shoebox but under 60x40x30cm. Large = bigger than that.

If multiple images are provided, they show the same item from different angles. Synthesise visible_text across all of them before identifying."""

    parts = [
        {"inline_data": {"mime_type": img.get("mime", "image/jpeg"), "data": img.get("base64", "")}}
        for img in image_items
    ]
    parts.append({"text": prompt})

    try:
        response = await gemini_client.generate_content(
            tier="pro",
            contents=[{"role": "user", "parts": parts}],
            tools=[{"google_search": {}}],
            generation_config={"maxOutputTokens": 4096, "temperature": 0.1},
            timeout=45.0,
            caller_context="vinted.identify_item",
        )
        text = gemini_client.extract_text(response)
        text = re.sub(r'```json|```', '', text).strip()
        return json.loads(text)
    except Exception:
        log.exception("[VINTED] identify_item failed, returning fallback")
        return fallback


async def research_sold_prices(search_query: str, item_name: str) -> Dict:
    """Search for real sold prices using Brave search."""
    if not BRAVE_API_KEY:
        return {"prices": [], "average": None, "source": "no_api_key"}

    try:
        # Search eBay sold listings
        ebay_query = f"site:ebay.co.uk sold {search_query}"
        vinted_query = f"site:vinted.co.uk {search_query}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                params={"q": ebay_query, "count": 5}
            )
            ebay_results = r.json().get("web", {}).get("results", [])

            r2 = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                params={"q": f"ebay sold completed {search_query} price", "count": 5}
            )
            price_results = r2.json().get("web", {}).get("results", [])

        # Extract price mentions from snippets
        all_snippets = " ".join([
            r.get("description", "") for r in ebay_results + price_results
        ])

        prices_found = re.findall(r'£(\d+(?:\.\d{2})?)', all_snippets)
        prices = [float(p) for p in prices_found if 1 < float(p) < 500]

        if prices:
            avg = sum(prices) / len(prices)
            min_p = min(prices)
            max_p = max(prices)
            # Suggest slightly below average for quick sale
            suggested = round(avg * 0.85, 0)
        else:
            avg = min_p = max_p = suggested = None

        return {
            "prices_found": prices[:10],
            "average": round(avg, 2) if avg else None,
            "min": round(min_p, 2) if min_p else None,
            "max": round(max_p, 2) if max_p else None,
            "suggested_price": suggested,
            "source": "brave_search",
            "snippets": [r.get("description", "")[:100] for r in price_results[:3]]
        }
    except Exception:
        log.exception("[VINTED] research_sold_prices failed, returning fallback")
        return {
            "prices_found": [],
            "average": None,
            "min": None,
            "max": None,
            "suggested_price": None,
            "source": "fallback",
            "snippets": [],
            "research_notes": "Unable to research recent sold prices. Price suggestion is based on item type only.",
            "_fallback": True,
        }


async def draft_listing(
    item_info: Dict,
    price_data: Dict,
    platform: str = "vinted",
    condition: str = "good"
) -> Dict:
    """Draft an optimised listing for Vinted or eBay."""
    def _build_fallback() -> Dict:
        brand = (item_info.get("brand") or "").strip()
        item_name = (item_info.get("item_name") or "Item").strip()
        color = (item_info.get("color") or "").strip()
        material = (item_info.get("material") or "").strip()
        condition_visible = (item_info.get("condition_visible") or condition or "used").strip()
        size = (item_info.get("estimated_size") or "").strip()
        features = item_info.get("key_features") or []
        if not isinstance(features, list):
            features = []

        title = f"{brand} {item_name}".strip() if brand else item_name
        if len(title) > 80:
            title = title[:77].rstrip() + "..."

        desc_parts = []
        desc_parts.append(f"{brand} {item_name}." if brand else f"{item_name}.")
        if condition_visible:
            desc_parts.append(f"Condition: {condition_visible}.")
        if size:
            desc_parts.append(f"Size: {size}.")
        if color:
            desc_parts.append(f"Colour: {color}.")
        if material:
            desc_parts.append(f"Material: {material}.")
        if features:
            desc_parts.append("Features: " + ", ".join(str(f) for f in features) + ".")
        desc_parts.append("Postage or collection available.")
        description = " ".join(desc_parts)

        sp = price_data.get("suggested_price")
        suggested_price = sp if sp else "See seller"

        return {
            "title": title,
            "description": description,
            "suggested_price": suggested_price,
            "condition": condition,
            "category_suggestion": item_info.get("category", ""),
            "tips": [],
            "parcel_size": item_info.get("parcel_size", "medium"),
            "_fallback": True,
        }

    if not GEMINI_API_KEY:
        log.warning("[VINTED] draft_listing: GEMINI_API_KEY not configured, using fallback")
        return _build_fallback()

    price_context = ""
    if price_data.get("suggested_price"):
        price_context = f"""
Sold price research:
- Average sold price: £{price_data.get('average', 'unknown')}
- Price range: £{price_data.get('min', '?')} - £{price_data.get('max', '?')}
- Suggested listing price: £{price_data.get('suggested_price', '?')} (slightly below average for quick sale)"""

    prompt = f"""Write an optimised {platform} listing for this item.

Item identified: {item_info.get('item_name', 'Unknown item')}
Brand: {item_info.get('brand', 'Unknown')}
Category: {item_info.get('category', 'Other')}
Size/dimensions: {item_info.get('estimated_size', 'See photos')}
Colour: {item_info.get('color', 'See photos')}
Material: {item_info.get('material', 'See photos')}
Condition from photo: {item_info.get('condition_visible', 'Good')}
Key features: {', '.join(item_info.get('key_features', []))}
{price_context}

Write a {platform} listing that:
- Has a compelling title (max 80 chars for eBay, 50 for Vinted)
- Clear, honest description of condition
- Mentions key selling points
- Uses natural language, not robotic
- Includes measurements/size prominently
- Ends with a note about postage/collection

Respond in JSON:
{{
    "title": "listing title",
    "description": "full listing description",
    "suggested_price": {price_data.get('suggested_price', 'null')},
    "condition": "{condition}",
    "category_suggestion": "best category to list in",
    "tips": ["one or two tips to increase chances of sale"]
}}"""

    try:
        response = await gemini_client.generate_content(
            tier="pro",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 4096, "temperature": 0.3},
            timeout=45.0,
            caller_context="vinted.draft_listing",
        )
        text = gemini_client.extract_text(response)
        text = re.sub(r'```json|```', '', text).strip()
        return json.loads(text)
    except Exception:
        log.exception("[VINTED] draft_listing failed, returning synthetic fallback")
        return _build_fallback()


async def full_listing_pipeline(
    image_base64: str = "",
    image_mime: str = "image/jpeg",
    platform: str = "vinted",
    condition: str = "good",
    user_notes: str = "",
    images: Optional[List[Dict]] = None,
) -> Dict:
    """
    Full pipeline: photo(s) → identification → price research → listing.
    Returns everything Tony needs to post the listing.
    """
    warnings = []

    # Step 1: Identify the item
    print("[VINTED] Identifying item from photo...")
    item_info = await identify_item(
        image_base64=image_base64,
        image_mime=image_mime,
        images=images,
    )
    if item_info.pop("_fallback", False):
        warnings.append("vision_identification")

    # Step 2: Research prices via Brave. Retained for reference URLs / snippets;
    # no longer the primary price source (Gemini's estimate wins if usable).
    search_query = item_info.get("search_query", item_info.get("item_name", ""))
    if search_query:
        print(f"[VINTED] Researching prices for: {search_query}")
        price_data = await research_sold_prices(search_query, item_info.get("item_name", ""))
    else:
        price_data = {}
    if price_data.pop("_fallback", False):
        warnings.append("price_research")

    # Step 2.5: Choose price source. Gemini's suggested_uk_resale_price is
    # primary if usable (positive int/float); otherwise fall back to Brave.
    gemini_price = item_info.get("suggested_uk_resale_price")
    if isinstance(gemini_price, (int, float)) and gemini_price > 0:
        effective_price_data = {
            "suggested_price": gemini_price,
            "source": "gemini",
            "reasoning": item_info.get("price_reasoning", ""),
        }
    else:
        effective_price_data = price_data

    # Step 3: Draft listing
    print("[VINTED] Drafting listing...")
    listing = await draft_listing(item_info, effective_price_data, platform, condition)
    if listing.pop("_fallback", False):
        warnings.append("listing_draft")

    return {
        "ok": True,
        "item": item_info,
        "listing": listing,
        "prices": price_data,
        "platform": platform,
        "warnings": warnings,
        "summary": (
            f"Listed: {item_info.get('item_name', 'Item')}"
            f" | Suggested price: £{listing.get('suggested_price', '?')}"
            f" | Platform: {platform}"
        ),
    }
