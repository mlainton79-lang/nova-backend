"""
Tony's Marketplace Intelligence.

Monitors online marketplaces for opportunities:
- Items selling cheap that are worth more on eBay
- Items Matthew is looking for
- Price trends for items he's selling

Uses web search since FB Marketplace doesn't have a public API.
Cross-references with eBay sold prices for arbitrage opportunities.
"""
import os
from datetime import datetime
from typing import List, Dict
from app.core.model_router import gemini_json
from app.core.brave_search import brave_search


async def find_arbitrage_opportunities(location: str = "Rotherham") -> List[Dict]:
    """
    Find items cheap on Facebook Marketplace worth more on eBay.
    Uses web search to find patterns.
    """
    searches = [
        f"Facebook Marketplace {location} cheap branded items 2026",
        "what sells for profit Facebook Marketplace to eBay UK 2026",
        f"bargains {location} area resell eBay profit",
    ]
    
    all_intel = ""
    for search in searches[:2]:
        try:
            result = await brave_search(search)
            if result:
                all_intel += result[:400] + "\n"
        except Exception:
            pass
    
    if not all_intel:
        return []
    
    prompt = f"""Tony is finding arbitrage opportunities for Matthew in the {location} area.

Matthew sells on Vinted and eBay. He can source from Facebook Marketplace and local car boots.

Market intelligence:
{all_intel[:1500]}

Identify specific arbitrage opportunities:
- Item category or specific brand
- Typical Facebook Marketplace price (buy)
- Typical eBay sold price (sell)
- Profit after fees (~13% eBay fee)
- Where to find them locally
- How fast they typically sell

Be specific and realistic. No generic advice.

Respond in JSON:
{{
    "opportunities": [
        {{
            "category": "specific item type",
            "buy_price": "£X-Y",
            "sell_price": "£X-Y",
            "profit_after_fees": "£X-Y",
            "source": "where to find locally",
            "sell_speed": "fast/medium/slow",
            "tip": "specific insider tip"
        }}
    ],
    "best_opportunity": "the single best opportunity right now"
}}"""
    
    result = await gemini_json(prompt, task="analysis", max_tokens=800)
    if result:
        opportunities = result.get("opportunities", [])
        if result.get("best_opportunity"):
            try:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="marketplace_opportunity",
                    title="Resale opportunity spotted",
                    body=result["best_opportunity"],
                    priority="normal",
                    source="marketplace_monitor"
                )
            except Exception:
                pass
        return opportunities
    return []


async def monitor_price_trends(items: List[str]) -> Dict:
    """Track price trends for specific items Matthew is selling."""
    if not items:
        return {}
    
    trends = {}
    for item in items[:3]:
        try:
            result = await brave_search(f"eBay sold {item} price 2026 UK")
            if result:
                prompt = f"""Extract eBay sold price data for: {item}

Search results: {result[:500]}

Respond in JSON:
{{
    "item": "{item}",
    "avg_sold_price": "£X",
    "price_range": "£X-Y",
    "trend": "rising/stable/falling",
    "best_condition_to_sell": "new/good/any"
}}"""
                trend = await gemini_json(prompt, task="analysis", max_tokens=200)
                if trend:
                    trends[item] = trend
        except Exception:
            pass
    
    return trends


async def run_marketplace_intelligence() -> Dict:
    """Full marketplace intelligence run."""
    results = {}
    
    try:
        opps = await find_arbitrage_opportunities()
        results["arbitrage_opportunities"] = opps
        print(f"[MARKETPLACE] Found {len(opps)} arbitrage opportunities")
    except Exception as e:
        print(f"[MARKETPLACE] Arbitrage search failed: {e}")
    
    return results
