"""
Tony's Anticipation Engine.

The highest expression of knowing someone well.

Tony doesn't wait to be asked. He predicts what Matthew needs
based on context, patterns, time, and situation.

Examples of genuine anticipation:
- It's 19:30 on a Sunday → Matthew has a night shift in 30 mins → 
  Tony checks if he's acknowledged it and sends a reminder
  
- Matthew mentioned something important days ago → no follow-up →
  Tony checks if there's been any email response and surfaces it

- Amelia's birthday is in 14 days → Tony noticed nothing has been planned →
  Tony surfaces this quietly

- Matthew hasn't messaged in 48h (unusual) → Tony checks if anything
  concerning happened in his emails or calendar

- YouTube trends show Stone Island is surging → 
  Tony knows Matthew sells on Vinted → creates actionable alert

This runs every 6h as part of the autonomous loop.
The output is not spam — Tony only surfaces things that genuinely matter.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def anticipate_shift_needs() -> List[Dict]:
    """Check if Matthew has a shift coming up and surface relevant things."""
    insights = []
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get upcoming calendar events
        cur.execute("""
            SELECT title, content FROM tony_living_memory 
            WHERE section = 'RECENT_EVENTS'
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        now = datetime.utcnow()
        
        # Night shift pattern: Matthew typically works 20:00-08:00
        if 17 <= now.hour <= 19:  # Late afternoon before typical night shift
            insights.append({
                "type": "shift_prep",
                "message": "If you're on tonight, shift starts at 20:00. Anything to sort before you go?",
                "priority": "normal"
            })
    except Exception as e:
        print(f"[ANTICIPATION] Shift check failed: {e}")
    return insights


async def check_unresolved_threads() -> List[Dict]:
    """Find things Matthew mentioned that were never resolved."""
    insights = []
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get open loops from living memory
        cur.execute("""
            SELECT content FROM tony_living_memory
            WHERE section = 'OPEN_LOOPS'
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row and row[0]:
            open_loops = row[0]
            if len(open_loops) > 20:
                # Parse open loops and check for stale ones
                prompt = f"""Tony is reviewing unresolved items for Matthew.

Open loops: {open_loops[:500]}

Which of these have been open for a while and need attention?
Focus on things that could have consequences if ignored.

Respond in JSON:
{{
    "urgent_unresolved": [
        {{
            "item": "what's unresolved",
            "consequence": "what happens if ignored",
            "suggestion": "what Tony should do"
        }}
    ]
}}

If nothing urgent: {{"urgent_unresolved": []}}"""

                result = await gemini_json(prompt, task="reasoning", max_tokens=400)
                if result:
                    for item in result.get("urgent_unresolved", [])[:2]:
                        insights.append({
                            "type": "unresolved_thread",
                            "message": f"{item.get('item', '')}: {item.get('consequence', '')}",
                            "priority": "high"
                        })
    except Exception as e:
        print(f"[ANTICIPATION] Thread check failed: {e}")
    return insights


async def anticipate_from_email_patterns() -> List[Dict]:
    """Check if any emails need a response that Tony hasn't flagged yet."""
    # No hardcoded topic search. Email anticipation is now driven by patterns Matthew
    # actively engages with in conversation, not hardcoded search terms.
    return []


async def run_anticipation_engine() -> List[Dict]:
    """Full anticipation run. Returns insights that need surfacing."""
    all_insights = []
    
    try:
        shift_insights = await anticipate_shift_needs()
        all_insights.extend(shift_insights)
    except Exception:
        pass
    
    try:
        thread_insights = await check_unresolved_threads()
        all_insights.extend(thread_insights)
    except Exception:
        pass
    
    try:
        email_insights = await anticipate_from_email_patterns()
        all_insights.extend(email_insights)
    except Exception:
        pass
    
    # Create alerts for high-priority anticipations
    for insight in all_insights:
        if insight.get("priority") == "high":
            try:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type="anticipation",
                    title="Tony noticed something",
                    body=insight.get("message", ""),
                    priority=insight.get("priority", "normal"),
                    source="anticipation_engine"
                )
            except Exception:
                pass
    
    if all_insights:
        print(f"[ANTICIPATION] Generated {len(all_insights)} anticipations")
    
    return all_insights
