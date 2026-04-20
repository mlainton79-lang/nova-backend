"""
Tony's Proactive Intelligence Engine.

Tony actively monitors things that matter to Matthew
and surfaces insights without being asked.

Monitors:
- Email patterns (new bills, correspondence that needs action)
- Legal developments (FCA enforcement, FOS decisions on similar cases)
- Market intelligence (item prices, trends)
- Calendar gaps (things not scheduled that should be)
- Goal drift (goals being ignored)
- Financial signals from emails

The output is a set of prioritised insights Tony surfaces
at the start of conversations or via WhatsApp.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List
from app.core.model_router import gemini_json
from app.core.brave_search import brave_search

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def scan_for_legal_developments() -> List[Dict]:
    """Monitor for FCA/FOS developments relevant to Matthew's case."""
    insights = []
    
    searches = [
"FOS payday loan irresponsible lending 2026 decision",
]
    
    for query in searches[:2]:
        try:
            results = await brave_search(query, count=3)
            if results and len(results) > 100:
                # Analyse relevance
                prompt = f"""These search results may be relevant to something Matthew is working on.

Search results:
{results[:800]}

Is there anything here that directly helps or affects Matthew's case?
- FOS decisions on similar cases?
- New legal precedents on irresponsible lending?

If nothing relevant: return null.
If relevant: explain in one sentence what it means for Matthew.

JSON: {{"relevant": true/false, "insight": "what this means for Matthew or null"}}"""

                result = await gemini_json(prompt, task="legal", max_tokens=200)
                if result and result.get("relevant") and result.get("insight"):
                    insights.append({
                        "type": "legal_development",
                        "insight": result["insight"],
                        "priority": "high"
                    })
        except Exception:
            pass
    
    return insights


async def scan_email_patterns() -> List[Dict]:
    """Analyse email patterns for things that need attention."""
    insights = []
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Check for recurring bills that might be overdue
        cur.execute("""
            SELECT source, COUNT(*) as count, MAX(event_date) as last_seen
            FROM tony_financial_events
            WHERE direction = 'out' AND created_at > NOW() - INTERVAL '60 days'
            GROUP BY source
            HAVING COUNT(*) >= 2
            ORDER BY last_seen ASC
        """)
        recurring = cur.fetchall()
        cur.close()
        conn.close()
        
        for source, count, last_seen in recurring:
            if last_seen:
                days_ago = (datetime.utcnow().date() - last_seen).days
                if days_ago > 35:  # Monthly bill overdue
                    insights.append({
                        "type": "bill_pattern",
                        "insight": f"{source} usually appears monthly — last seen {days_ago} days ago. May be overdue.",
                        "priority": "normal"
                    })
    except Exception as e:
        print(f"[PROACTIVE_INTEL] Email pattern scan failed: {e}")
    
    return insights


async def check_goal_staleness() -> List[Dict]:
    """Find goals that haven't had any progress in a while."""
    insights = []
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT title, priority, updated_at, progress_notes
            FROM tony_goals
            WHERE status = 'active'
            AND updated_at < NOW() - INTERVAL '14 days'
            AND priority IN ('urgent', 'high')
            ORDER BY priority, updated_at ASC
            LIMIT 3
        """)
        stale = cur.fetchall()
        cur.close()
        conn.close()
        
        for title, priority, updated, notes in stale:
            days_stale = (datetime.utcnow() - updated.replace(tzinfo=None)).days if updated else 99
            insights.append({
                "type": "stale_goal",
                "insight": f"'{title}' ({priority} priority) has had no progress in {days_stale} days.",
                "priority": "high" if priority == "urgent" else "normal"
            })
    except Exception as e:
        print(f"[PROACTIVE_INTEL] Goal staleness check failed: {e}")
    
    return insights


async def run_proactive_intelligence() -> List[Dict]:
    """Full proactive intelligence run."""
    all_insights = []
    
    for scan_fn in [
        scan_for_legal_developments,
        scan_email_patterns,
        check_goal_staleness,
    ]:
        try:
            insights = await scan_fn()
            all_insights.extend(insights)
        except Exception as e:
            print(f"[PROACTIVE_INTEL] Scan error: {e}")
    
    # Create alerts for high-priority insights
    for insight in all_insights:
        if insight.get("priority") == "high":
            try:
                from app.core.proactive import create_alert
                create_alert(
                    alert_type=insight.get("type", "intelligence"),
                    title="Tony spotted something",
                    body=insight.get("insight", ""),
                    priority="high",
                    source="proactive_intelligence"
                )
            except Exception:
                pass
    
    if all_insights:
        print(f"[PROACTIVE_INTEL] Generated {len(all_insights)} proactive insights")
    
    return all_insights
