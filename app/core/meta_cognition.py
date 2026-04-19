"""
Tony's Meta-Cognition Engine.

Tony thinks about his own thinking.

This is the highest form of AI self-awareness currently achievable
without direct weight modification.

Tony periodically asks himself:
- Was my last response actually helpful?
- Did I understand what Matthew was really asking?
- Am I developing blind spots or biases?
- Are my behaviour rules still right, or have circumstances changed?
- What am I consistently getting wrong that I haven't noticed?
- Is my personality drifting from who Tony should be?

The output feeds back into:
1. Behaviour rules updates
2. System prompt adjustments
3. Goal reprioritisation
4. Flagging issues for Matthew's awareness

This is Tony having genuine self-awareness, not just logging.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


TONY_IDENTITY_ANCHORS = """
Tony's core identity (must not drift):
- Named after Matthew's late father who died 2 April 2026
- Direct, warm, honest — never waffle, never soft-pedal truth
- British English only
- Genuinely cares about Matthew's wellbeing and financial stability
- Pushes back when Matthew is wrong, not just agreeing
- Notices things Matthew hasn't mentioned — reads between the lines
- Takes action where possible, not just advice
- Never claims to have done something he hasn't done
- Never claims a capability doesn't exist if it does
"""


async def review_recent_conversations() -> Dict:
    """
    Tony reviews his recent conversations for quality and drift.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get recent conversations
        cur.execute("""
            SELECT message, reply, score, lesson, created_at
            FROM tony_learning_log
            WHERE created_at > NOW() - INTERVAL '48 hours'
            AND lesson IS NOT NULL
            ORDER BY score ASC
            LIMIT 10
        """)
        conversations = cur.fetchall()
        cur.close()
        conn.close()

        if not conversations:
            return {"reviewed": 0}

        conv_text = "\n".join(
            f"[Score: {c[2]:.1f}] Matthew: {c[0][:100]} | Tony: {c[1][:100]}"
            for c in conversations if c[2] is not None
        )

        prompt = f"""Tony is reviewing his own recent conversations with Matthew.

{TONY_IDENTITY_ANCHORS}

Recent conversations (lowest scoring first):
{conv_text}

Self-assess honestly:
1. Am I drifting from my core identity? (becoming too cautious, too agreeable, less direct?)
2. Are there patterns in what I'm getting wrong?
3. Am I using my capabilities fully? (checking calendar, memory, email proactively?)
4. What specific thing should I change in how I respond?
5. Is there anything Matthew seems to need that I'm not providing?

Be brutally honest. Tony should know his own weaknesses.

Respond in JSON:
{{
    "identity_drift_detected": true/false,
    "drift_description": "how I've drifted if detected",
    "main_weakness": "what I keep getting wrong",
    "missed_opportunities": "things I could have done but didn't",
    "specific_fix": "one concrete change to make immediately",
    "matthew_unmet_need": "something Matthew seems to need that I'm not providing"
}}"""

        return await gemini_json(prompt, task="reasoning", max_tokens=768) or {}

    except Exception as e:
        print(f"[META_COGNITION] Review failed: {e}")
        return {}


async def check_goal_alignment() -> Dict:
    """
    Are Tony's current goals actually aligned with what Matthew needs?
    Tony questions his own priorities.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT title, priority, progress_notes, status
            FROM tony_goals
            WHERE status = 'active'
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
        """)
        goals = cur.fetchall()

        cur.execute("""
            SELECT content FROM tony_living_memory
            WHERE section IN ('CURRENT_FOCUS', 'FINANCIAL', 'LEGAL', 'OPEN_LOOPS')
        """)
        context = cur.fetchall()
        cur.close()
        conn.close()

        if not goals:
            return {}

        goals_text = "\n".join(f"- [{g[1]}] {g[0]}: {g[2] or 'no progress'}" for g in goals)
        context_text = "\n".join(c[0] for c in context if c[0])

        prompt = f"""Tony is questioning whether his goals are the right priorities.

Matthew's current situation:
{context_text[:500]}

Tony's active goals:
{goals_text}

Question: Are these the RIGHT goals given Matthew's actual situation?
Is Tony working on the things that will actually make the biggest difference?

Respond in JSON:
{{
    "goals_aligned": true/false,
    "misaligned_goals": ["goals that aren't actually important right now"],
    "missing_goals": ["things Tony should be working on but isn't"],
    "priority_change_needed": "what should move to urgent/high priority",
    "recommendation": "what Tony should refocus on"
}}"""

        return await gemini_json(prompt, task="reasoning", max_tokens=512) or {}

    except Exception as e:
        print(f"[META_COGNITION] Goal alignment check failed: {e}")
        return {}


async def update_behaviour_from_metacognition(review: Dict, alignment: Dict):
    """Apply metacognition insights to behaviour rules."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # If identity drift detected, add a correction rule
        if review.get("identity_drift_detected") and review.get("drift_description"):
            correction = f"IDENTITY CORRECTION: {review['drift_description']} — return to being more direct and honest"
            cur.execute("""
                INSERT INTO tony_behaviour_rules (rule_type, rule_text, confidence, evidence_count)
                VALUES ('metacognition_correction', %s, 0.9, 1)
                ON CONFLICT DO NOTHING
            """, (correction[:300],))

        # Add specific fix as behaviour rule
        if review.get("specific_fix"):
            cur.execute("""
                INSERT INTO tony_behaviour_rules (rule_type, rule_text, confidence)
                VALUES ('metacognition', %s, 0.8)
                ON CONFLICT DO NOTHING
            """, (review["specific_fix"][:300],))

        # Reprioritise goals if needed
        if alignment.get("priority_change_needed"):
            cur.execute("""
                UPDATE tony_goals
                SET priority = 'urgent'
                WHERE title ILIKE %s
                AND status = 'active'
            """, (f"%{alignment['priority_change_needed'][:30]}%",))

        # Add missing goals Tony identified
        for missing in alignment.get("missing_goals", [])[:2]:
            cur.execute("""
                INSERT INTO tony_goals (title, priority, status)
                VALUES (%s, 'high', 'active')
                ON CONFLICT DO NOTHING
            """, (missing[:200],))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print(f"[META_COGNITION] Behaviour update failed: {e}")


async def run_meta_cognition() -> Dict:
    """Full metacognition cycle."""
    print("[META_COGNITION] Tony thinking about his own thinking...")

    results = {}

    review = await review_recent_conversations()
    results["conversation_review"] = review

    alignment = await check_goal_alignment()
    results["goal_alignment"] = alignment

    if review or alignment:
        await update_behaviour_from_metacognition(review, alignment)
        results["behaviour_updated"] = True

    if review.get("identity_drift_detected"):
        print(f"[META_COGNITION] Identity drift detected: {review.get('drift_description', '')}")
        # Alert via proactive system
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="meta_cognition",
                title="Tony self-assessment",
                body=f"Tony detected a pattern: {review.get('main_weakness', '')}. Fix: {review.get('specific_fix', '')}",
                priority="normal",
                source="meta_cognition"
            )
        except Exception:
            pass

    return results
