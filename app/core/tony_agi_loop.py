"""
Tony's AGI Loop — The Continuous Self-Improvement Engine.

This is the highest-level autonomous process Tony runs.
It's what makes the difference between a tool and a thinking agent.

Every 6 hours Tony:
1. Reviews his current state honestly
2. Identifies the single most impactful gap
3. Researches the best approach
4. Builds the solution
5. Deploys it
6. Moves to the next gap

Tony's improvement priorities (in order):
1. Things that fail — fix what's broken first
2. Things Matthew asked for — build what was requested  
3. Things that would generate income — high ROI capabilities
4. Things that make Tony smarter — deeper reasoning
5. Things that give Tony more autonomy — reduce reliance on Matthew

Tony tracks everything he builds and why, maintaining
a genuine record of his own development.
"""
import os
import asyncio
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.core.model_router import gemini_json, gemini

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


TONY_IMPROVEMENT_PRIORITIES = [
    {
        "name": "Fix broken capabilities",
        "check": "look at recent eval failures and error logs",
        "priority": 1
    },
    {
        "name": "Improve response quality",
        "check": "analyse recent conversation scores below 7",
        "priority": 2
    },
    {
        "name": "Expand income capabilities",
        "check": "what selling/income tools would help Matthew most",
        "priority": 3
    },
    {
        "name": "Deepen autonomy",
        "check": "what tasks does Matthew still have to do manually",
        "priority": 4
    },
    {
        "name": "Improve intelligence",
        "check": "what reasoning gaps are most frequent",
        "priority": 5
    }
]


async def assess_current_state() -> Dict:
    """Tony honestly assesses his current state."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Recent failures
        cur.execute("""
            SELECT COUNT(*) FROM tony_eval_log 
            WHERE success = FALSE 
            AND created_at > NOW() - INTERVAL '24 hours'
        """)
        failures = cur.fetchone()[0] if cur.rowcount else 0
        
        # Avg conversation score
        cur.execute("""
            SELECT AVG(score) FROM tony_learning_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            AND score IS NOT NULL
        """)
        avg_score = cur.fetchone()[0] or 0
        
        # What Tony built autonomously
        cur.execute("""
            SELECT COUNT(*) FROM think_sessions
            WHERE stage = 'autonomous_build_success'
        """)
        builds = cur.fetchone()[0] or 0
        
        # Recent pattern insights
        cur.execute("""
            SELECT content FROM tony_living_memory
            WHERE section = 'OPEN_LOOPS'
        """)
        open_loops = cur.fetchone()
        
        # Build log - recent attempts
        try:
            cur.execute("""
                SELECT stage, content, success FROM tony_build_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 5
            """)
            recent_builds = cur.fetchall()
        except Exception:
            recent_builds = []
        
        cur.close()
        conn.close()
        
        return {
            "recent_failures": failures,
            "avg_score": float(avg_score or 0),
            "autonomous_builds": builds,
            "open_loops": open_loops[0] if open_loops else "",
            "recent_build_attempts": [
                {"stage": r[0], "content": r[1][:100], "success": r[2]}
                for r in recent_builds
            ]
        }
    except Exception as e:
        print(f"[AGI_LOOP] State assessment failed: {e}")
        return {}


async def decide_what_to_build(state: Dict) -> Optional[Dict]:
    """
    Tony decides what to build next based on honest self-assessment.
    Uses Pro model for this critical decision.
    """
    state_summary = f"""
Recent failures: {state.get('recent_failures', 0)}
Avg response quality score: {state.get('avg_score', 0):.1f}/10
Capabilities built autonomously: {state.get('autonomous_builds', 0)}
Open loops: {state.get('open_loops', 'none')[:200]}
Recent build attempts: {state.get('recent_build_attempts', [])}
"""

    prompt = f"""Tony is an AI assistant for Matthew Lainton. Tony is deciding what to build next to improve himself.

Tony's current state:
{state_summary}

Tony's stack: FastAPI on Railway, PostgreSQL with pgvector, Python 3.12

What Matthew needs most right now (from context):
- Western Circle CCJ case needs active legal correspondence management
- Income from Vinted/eBay selling needs to be more automated
- Tony needs to act more autonomously without Matthew having to ask
- Financial awareness (Open Banking hasn't worked yet)
- Tony should be able to self-improve more reliably

What should Tony build next? Consider:
1. What's most broken that needs fixing?
2. What would have the highest impact on Matthew's life?
3. What's achievable in a single focused build session?
4. What builds toward genuine autonomy?

Respond in JSON:
{{
    "capability_name": "short name",
    "capability_description": "detailed description of what to build",
    "why_now": "why this is the highest priority right now",
    "impact": "what this changes for Matthew",
    "test_endpoint": "/api/v1/endpoint_to_test_after_deploy or null",
    "estimated_lines": "estimated lines of code",
    "priority_score": 1-10
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=1024)


async def run_agi_improvement_cycle() -> Dict:
    """
    Tony's full AGI self-improvement cycle.
    Runs every 6 hours as part of the autonomous loop.
    """
    print("[AGI_LOOP] Starting improvement cycle...")
    
    # Assess current state
    state = await assess_current_state()
    
    # Decide what to build
    decision = await decide_what_to_build(state)
    
    if not decision:
        print("[AGI_LOOP] Could not decide what to build")
        return {"ok": False, "reason": "decision_failed"}
    
    capability = decision.get("capability_name", "")
    description = decision.get("capability_description", "")
    
    if not capability or not description:
        print("[AGI_LOOP] Invalid decision")
        return {"ok": False, "reason": "invalid_decision"}
    
    print(f"[AGI_LOOP] Decided to build: {capability}")
    print(f"[AGI_LOOP] Why: {decision.get('why_now', '')}")
    print(f"[AGI_LOOP] Impact: {decision.get('impact', '')}")
    
    # Build it
    from app.core.tony_self_builder import tony_build_capability
    result = await tony_build_capability(
        capability,
        description,
        test_endpoint=decision.get("test_endpoint")
    )
    
    result["decision"] = decision
    result["state_at_build"] = state
    
    if result.get("success"):
        print(f"[AGI_LOOP] ✓ Built and deployed: {capability}")
        
        # Store achievement
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO think_sessions (stage, content)
                VALUES ('agi_build_success', %s)
            """, (f"Built {capability}: {decision.get('impact', '')}",))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass
    else:
        print(f"[AGI_LOOP] ✗ Build failed: {capability}")
    
    return result
