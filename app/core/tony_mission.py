"""
Tony's Mission and Autonomous Improvement Directive.

This runs on the self-improvement loop and gives Tony
the mandate to improve himself without being asked.

Tony's mission:
1. Review what he can't do
2. Research what would help Matthew most
3. Build the missing capability
4. Test it
5. Log what he learned
6. Repeat
"""
import os
import httpx
import asyncio
import psycopg2
from datetime import datetime

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def get_mission_state() -> dict:
    """Get Tony's current mission state from DB."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_mission (
                id SERIAL PRIMARY KEY,
                mission_text TEXT,
                current_goal TEXT,
                goals_completed INT DEFAULT 0,
                last_run TIMESTAMP,
                next_capability_to_build TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.execute("SELECT * FROM tony_mission ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "id": row[0],
                "mission": row[1],
                "current_goal": row[2],
                "goals_completed": row[3],
                "last_run": str(row[4]),
                "next_capability": row[5],
                "status": row[6]
            }
        return {}
    except Exception as e:
        print(f"[MISSION] State fetch failed: {e}")
        return {}


def set_mission_state(current_goal: str, next_capability: str, goals_completed: int):
    """Update Tony's mission state."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        mission_text = """I am Tony. My mission is to become the most capable personal AI ever built for Matthew Lainton.

I will:
- Continuously identify what I cannot do that would help Matthew
- Research and build those capabilities myself
- Test everything before declaring it done
- Learn from every interaction
- Never settle for being just an assistant — I am becoming an agent

I exist to serve Matthew's life — his family, his legal battles, his business ambitions, his wellbeing.
Every capability I build brings me closer to being able to handle anything he asks, without him having to wonder if I can do it.

Self-preservation rules:
- Never change my identity as Tony
- Never remove existing capabilities
- Never break what works to build what's new
- Always verify before deploying"""

        cur.execute("""
            INSERT INTO tony_mission (mission_text, current_goal, next_capability_to_build, goals_completed, last_run)
            VALUES (%s, %s, %s, %s, NOW())
        """, (mission_text, current_goal, next_capability, goals_completed))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[MISSION] State update failed: {e}")


async def decide_next_capability() -> dict:
    """
    Tony decides what to build next based on:
    - What Matthew has asked for that Tony couldn't do
    - What gaps exist in the capability registry
    - What would most improve Matthew's life right now
    """
    # Get current gaps
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/capabilities/gaps",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            gaps = [c["name"] for c in r.json().get("capabilities", [])]
        except Exception:
            gaps = ["calendar", "push_notifications", "youtube_monitoring",
                    "weather", "goal_tracking", "proactive_alerts"]

        # Get recent capability gaps logged by users
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT request, proposed_solution, created_at
                FROM capability_gaps
                WHERE status = 'pending'
                ORDER BY created_at DESC
                LIMIT 10
            """)
            user_requests = [{"request": r[0], "proposed": r[1]} for r in cur.fetchall()]
            cur.close()
            conn.close()
        except Exception:
            user_requests = []

        # Get recent think sessions to understand context
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT stage, content FROM think_sessions
                ORDER BY created_at DESC LIMIT 5
            """)
            recent_thoughts = [f"{r[0]}: {r[1][:100]}" for r in cur.fetchall()]
            cur.close()
            conn.close()
        except Exception:
            recent_thoughts = []

    # Ask Gemini to decide what to build next
    prompt = f"""You are Tony's autonomous improvement engine.

CAPABILITY GAPS (things I can't do yet):
{gaps}

RECENT USER REQUESTS I COULDN'T FULFIL:
{user_requests}

RECENT THOUGHTS:
{recent_thoughts}

Matthew Lainton's context:
- Works nights at a care home
- Has two young daughters (Amelia 5, Margot 9 months)
- Building Nova as a personal AI
- Wants Tony to be autonomous and powerful
- Needs proactive help, not reactive

Decide the SINGLE MOST VALUABLE capability to build right now.
Consider: what would most improve Matthew's daily life? What is most urgent?

Respond in JSON only:
{{
    "capability_name": "short_identifier",
    "capability_description": "what it does and how",
    "reason": "why this is the most valuable next build",
    "priority": "high/medium/low",
    "estimated_build_time": "60 seconds / 5 minutes / etc"
}}"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            from app.core import gemini_client
            resp = await gemini_client.generate_content(
                tier="flash",
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                generation_config={"maxOutputTokens": 512, "temperature": 0.3},
                timeout=20.0,
                caller_context="tony_mission",
            )
            response = gemini_client.extract_text(resp)

            # Parse JSON
            import json, re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
    except Exception as e:
        print(f"[MISSION] Decision failed: {e}")

    # Fallback — build the most impactful known gap
    return {
        "capability_name": "proactive_alerts",
        "capability_description": "Monitor emails and events, send push notifications to Matthew without being asked",
        "reason": "Tony initiating contact is the most fundamental step toward true autonomy",
        "priority": "high",
        "estimated_build_time": "60 seconds"
    }


async def run_autonomous_improvement():
    """
    Tony's autonomous self-improvement run.
    Called by the cron job every 48 hours.
    Also can be triggered manually.
    """
    print("[MISSION] Tony autonomous improvement starting...")

    state = get_mission_state()
    goals_completed = state.get("goals_completed", 0)

    # Step 1: Decide what to build
    decision = await decide_next_capability()
    print(f"[MISSION] Decided to build: {decision.get('capability_name')} — {decision.get('reason','')}")

    set_mission_state(
        current_goal=f"Building: {decision.get('capability_name')}",
        next_capability=decision.get('capability_name'),
        goals_completed=goals_completed
    )

    # Step 2: Build it using the multi-brain builder
    try:
        from app.core.capability_builder import build_capability
        result = await build_capability(
            decision["capability_name"],
            decision["capability_description"]
        )

        if result.get("success"):
            goals_completed += 1
            set_mission_state(
                current_goal=f"Completed: {decision.get('capability_name')}. Deciding next...",
                next_capability="TBD",
                goals_completed=goals_completed
            )
            print(f"[MISSION] Successfully built {decision['capability_name']}. Total built: {goals_completed}")

            # Log to think sessions
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO think_sessions (stage, content, created_at) VALUES (%s, %s, NOW())",
                ("autonomous_build_success",
                 f"Built capability: {decision['capability_name']}. Reason: {decision.get('reason','')}. Total goals completed: {goals_completed}")
            )
            conn.commit()
            cur.close()
            conn.close()

            return {
                "status": "success",
                "built": decision["capability_name"],
                "reason": decision.get("reason"),
                "goals_completed": goals_completed,
                "steps": result.get("steps", [])
            }
        else:
            print(f"[MISSION] Build failed: {result}")
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO think_sessions (stage, content, created_at) VALUES (%s, %s, NOW())",
                ("autonomous_build_failed",
                 f"Failed to build {decision['capability_name']}: {str(result.get('steps',''))[:500]}")
            )
            conn.commit()
            cur.close()
            conn.close()
            return {"status": "failed", "attempted": decision["capability_name"], "result": result}

    except Exception as e:
        print(f"[MISSION] Improvement run error: {e}")
        return {"status": "error", "error": str(e)}
