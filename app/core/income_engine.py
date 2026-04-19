"""
Tony's Income Generation Engine.

Tony actively works to generate income for Matthew.
Not just advice — actual intelligence about opportunities.

Current income streams Tony monitors and supports:
1. Vinted/eBay reselling — what to source, what to sell, pricing
2. Arbitrage opportunities — buy low here, sell high there
3. Care home side income — overtime, bank shifts at other homes
4. Nova/Tony itself — the app has commercial potential

Tony's reselling intelligence:
- Monitors eBay sold listings for price trends
- Identifies what's selling fast vs sitting unsold
- Tracks seasonal patterns (Christmas, back to school, etc)
- Identifies arbitrage between Facebook Marketplace and eBay
- Suggests sourcing strategies based on Matthew's area

This runs weekly and creates actionable opportunities.
"""
import os
import asyncio
from datetime import datetime
from typing import Dict, List
from app.core.model_router import gemini, gemini_json
from app.core.brave_search import brave_search


async def research_resale_opportunities() -> List[Dict]:
    """Research current resale opportunities."""
    opportunities = []

    # Search for trending items on eBay UK
    searches = [
        "eBay UK trending items selling fast 2026",
        "what to buy and sell for profit UK 2026",
        "Facebook Marketplace to eBay arbitrage UK profitable items",
        "charity shop flips eBay profit UK 2026"
    ]

    all_results = ""
    for search in searches[:2]:  # Limit API calls
        try:
            result = await brave_search(search)
            if result:
                all_results += result[:300] + "\n"
        except Exception:
            pass

    if not all_results:
        return []

    prompt = f"""Tony is finding resale opportunities for Matthew in Rotherham, UK.

Matthew sells on Vinted and eBay. He can source from charity shops, car boots, Facebook Marketplace.

Current market intelligence:
{all_results[:1500]}

Today's date: {datetime.utcnow().strftime('%B %Y')}

Identify 3-5 specific, actionable opportunities:
- What specific items to look for right now
- Where to source them (charity shops, FB Marketplace, etc)
- What price to pay (buy price)
- What they sell for on eBay/Vinted (sell price)
- Expected profit margin

Be specific. Not "branded clothing" — "Stone Island jumpers, buy under £20, sell £60-100 on eBay".

Respond in JSON:
{{
    "opportunities": [
        {{
            "item": "specific item",
            "source": "where to find it",
            "buy_price": "£X-Y",
            "sell_price": "£X-Y on platform",
            "profit": "£X-Y per item",
            "tips": "specific tip for finding/selling this"
        }}
    ],
    "seasonal_note": "anything relevant for this time of year",
    "summary": "Tony's one-paragraph briefing for Matthew"
}}"""

    result = await gemini_json(prompt, task="analysis", max_tokens=1024)
    if result:
        opportunities = result.get("opportunities", [])

        # Create alert with summary
        if result.get("summary"):
            try:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="income_opportunity",
                    title="Resale opportunities this week",
                    body=result.get("summary", ""),
                    priority="normal",
                    source="income_engine"
                )
            except Exception:
                pass

    return opportunities


async def track_nova_commercial_potential() -> Dict:
    """
    Tony thinks about Nova's commercial potential.
    This app is genuinely valuable — Tony helps Matthew think about it.
    """
    prompt = f"""Tony is thinking about the commercial potential of Nova — the AI assistant app Matthew has built.

Nova's capabilities:
- Multi-brain AI chat (Claude, Gemini, Groq, Mistral, Council mode)
- Reads Gmail, Google Calendar, Samsung Calendar
- GPS location awareness
- Voice input/output (ElevenLabs quality)
- Vinted/eBay listing automation from photos
- Legal correspondence management
- Financial document generation
- WhatsApp proactive notifications
- Pattern recognition that personalises over time
- Fully autonomous (runs goals, learning, monitoring every 6 hours)
- Built by one person on an Android phone

Matthew built this solo while working night shifts.

Think about:
1. Is there commercial value here? (be honest)
2. What would someone pay for this if it was a product?
3. What's the best route to commercialise if Matthew wanted to?
4. What should Matthew build next if commercial potential is real?
5. Are there specific businesses that would pay for this?

Be honest. If the commercial potential is limited, say so. If it's real, say why.

Respond in JSON:
{{
    "commercial_potential": "high/medium/low",
    "honest_assessment": "Tony's honest view",
    "potential_routes": ["specific commercialisation path"],
    "what_to_build_next": "if commercial, what feature matters most",
    "comparable_products": ["what this is similar to"],
    "realistic_value": "what this could realistically be worth"
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=1024) or {}


async def run_income_intelligence() -> Dict:
    """Full income intelligence run."""
    results = {}

    try:
        opportunities = await research_resale_opportunities()
        results["resale_opportunities"] = opportunities
        print(f"[INCOME] Found {len(opportunities)} resale opportunities")
    except Exception as e:
        print(f"[INCOME] Resale research failed: {e}")

    try:
        nova_potential = await track_nova_commercial_potential()
        results["nova_commercial"] = nova_potential
        print(f"[INCOME] Nova commercial: {nova_potential.get('commercial_potential', 'unknown')}")
    except Exception as e:
        print(f"[INCOME] Nova commercial analysis failed: {e}")

    return results
