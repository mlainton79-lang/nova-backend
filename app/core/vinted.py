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
import httpx
from typing import Dict, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


async def identify_item(image_base64: str, image_mime: str = "image/jpeg") -> Dict:
    """Use Gemini Vision to identify what the item is."""
    if not GEMINI_API_KEY:
        return {"error": "Gemini not configured"}

    prompt = """You are helping sell an item on Vinted/eBay. Identify this item precisely.

Return JSON only:
{
    "item_name": "specific product name e.g. Nike Air Max 90 trainers",
    "brand": "brand name or Unknown",
    "category": "clothing/footwear/electronics/homeware/toys/other",
    "estimated_size": "size if clothing/footwear, or dimensions if other",
    "condition_visible": "what condition does it appear to be in from the photo",
    "key_features": ["notable features that affect value"],
    "search_query": "best search query to find sold prices on eBay e.g. Nike Air Max 90 size 9"
}"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{
                        "role": "user",
                        "parts": [
                            {"inline_data": {"mime_type": image_mime, "data": image_base64}},
                            {"text": prompt}
                        ]
                    }],
                    "generationConfig": {"maxOutputTokens": 512, "temperature": 0.1}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r'```json|```', '', text).strip()
            return json.loads(text)
    except Exception as e:
        return {"error": str(e)}


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
    except Exception as e:
        return {"error": str(e), "prices": []}


async def draft_listing(
    item_info: Dict,
    price_data: Dict,
    platform: str = "vinted",
    condition: str = "good"
) -> Dict:
    """Draft an optimised listing for Vinted or eBay."""
    if not GEMINI_API_KEY:
        return {"error": "Gemini not configured"}

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
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.3}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r'```json|```', '', text).strip()
            return json.loads(text)
    except Exception as e:
        return {"error": str(e)}


async def full_listing_pipeline(
    image_base64: str,
    image_mime: str = "image/jpeg",
    platform: str = "vinted",
    condition: str = "good",
    user_notes: str = ""
) -> Dict:
    """
    Full pipeline: photo → identification → price research → listing.
    Returns everything Tony needs to post the listing.
    """
    result = {"ok": False, "steps": {}}

    # Step 1: Identify the item
    print("[VINTED] Identifying item from photo...")
    item_info = await identify_item(image_base64, image_mime)
    result["steps"]["identification"] = item_info

    if "error" in item_info:
        result["error"] = f"Could not identify item: {item_info['error']}"
        return result

    result["item"] = item_info

    # Step 2: Research prices
    search_query = item_info.get("search_query", item_info.get("item_name", ""))
    if search_query:
        print(f"[VINTED] Researching prices for: {search_query}")
        price_data = await research_sold_prices(search_query, item_info.get("item_name", ""))
        result["steps"]["price_research"] = price_data
        result["prices"] = price_data
    else:
        price_data = {}

    # Step 3: Draft listing
    print("[VINTED] Drafting listing...")
    listing = await draft_listing(item_info, price_data, platform, condition)
    result["steps"]["listing"] = listing

    if "error" not in listing:
        result["ok"] = True
        result["listing"] = listing
        result["platform"] = platform
        result["summary"] = (
            f"Listed: {item_info.get('item_name', 'Item')}"
            f" | Suggested price: £{listing.get('suggested_price', '?')}"
            f" | Platform: {platform}"
        )

    return result
