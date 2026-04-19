"""
Tony's Learning Engine — Upgraded.

Tony learns from every conversation with Matthew.
Not just what was said, but what it means about how to help better.

Three learning loops:
1. INSTANT: After every message — extract facts, update patterns
2. SESSION: After every conversation — what went well, what didn't
3. WEEKLY: Deep synthesis — what am I getting wrong, what should change

The weekly synthesis is the most powerful:
Tony reads all his conversations, identifies recurring issues,
and rewrites his own behaviour rules.

This is the foundation of genuine improvement over time.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_learning_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_learning_log (
                id SERIAL PRIMARY KEY,
                message TEXT,
                reply TEXT,
                score FLOAT,
                lesson TEXT,
                provider TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_behaviour_rules (
                id SERIAL PRIMARY KEY,
                rule_type TEXT NOT NULL,
                rule_text TEXT NOT NULL UNIQUE,
                confidence FLOAT DEFAULT 0.5,
                evidence_count INTEGER DEFAULT 1,
                source TEXT DEFAULT 'learning',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[LEARNING] Tables initialised")
    except Exception as e:
        print(f"[LEARNING] Init failed: {e}")


async def score_conversation(message: str, reply: str) -> Optional[float]:
    """
    Tony scores his own response. Honest self-assessment.
    Returns 1-10 score.
    """
    prompt = f"""Score this AI response honestly on a 1-10 scale.

User message: {message[:200]}
Tony's reply: {reply[:300]}

Scoring criteria:
- Did Tony directly answer the question? (0-3 points)
- Was Tony genuinely helpful or just performative? (0-2 points)
- Was Tony's tone right — direct but warm, not generic? (0-2 points)
- Did Tony use available context/memory appropriately? (0-2 points)
- Did Tony take action where possible vs just advising? (0-1 point)

Return ONLY a decimal number between 1.0 and 10.0. Nothing else."""

    result = await gemini(prompt, task="analysis", max_tokens=10, temperature=0.1)
    try:
        return min(10.0, max(1.0, float(result.strip())))
    except Exception:
        return None


async def extract_lesson(message: str, reply: str, score: float) -> Optional[str]:
    """Extract a specific lesson from this conversation."""
    if score >= 8.0:
        return None  # No lesson needed from good responses

    prompt = f"""Tony gave a mediocre response (score: {score:.1f}/10).

User asked: {message[:200]}
Tony replied: {reply[:300]}

What ONE specific thing should Tony do differently next time?
Be concrete. Not "be more helpful" — say exactly what should change.
10 words or less."""

    return await gemini(prompt, task="analysis", max_tokens=50, temperature=0.2)


async def log_conversation(message: str, reply: str, provider: str = "gemini"):
    """Log a conversation and extract learnings."""
    score = await score_conversation(message, reply)
    lesson = None
    if score and score < 8.0:
        lesson = await extract_lesson(message, reply, score)

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_learning_log (message, reply, score, lesson, provider)
            VALUES (%s, %s, %s, %s, %s)
        """, (message[:500], reply[:500], score, lesson[:200] if lesson else None, provider))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LEARNING] Log failed: {e}")


async def run_weekly_learning_synthesis():
    """
    Tony's weekly deep learning synthesis.
    Reads all recent conversations and rewrites behaviour rules.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get all low-scoring conversations from last 7 days
        cur.execute("""
            SELECT message, reply, score, lesson
            FROM tony_learning_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            AND score IS NOT NULL
            ORDER BY score ASC
            LIMIT 20
        """)
        conversations = cur.fetchall()

        # Get current behaviour rules
        cur.execute("""
            SELECT rule_text FROM tony_behaviour_rules
            WHERE confidence > 0.6
            ORDER BY evidence_count DESC LIMIT 10
        """)
        current_rules = [r[0] for r in cur.fetchall()]

        cur.close()
        conn.close()

        if not conversations:
            return {"synthesised": False, "reason": "no conversations to learn from"}

        avg_score = sum(c[2] for c in conversations if c[2]) / max(len(conversations), 1)

        conv_text = "\n".join(
            f"[{c[2]:.1f}] {c[0][:80]} → {c[3] or 'no lesson'}"
            for c in conversations if c[2]
        )

        prompt = f"""Tony is synthesising a week of conversations to improve his behaviour.

Average response quality: {avg_score:.1f}/10
Current behaviour rules: {current_rules[:5]}

Weak conversations this week:
{conv_text[:2000]}

Synthesise:
1. What patterns of failure are recurring?
2. What 3 new behaviour rules would fix the most common issues?
3. Which current rules are working and should be reinforced?
4. What ONE thing would most improve Tony's quality next week?

Respond in JSON:
{{
    "new_rules": [
        {{"rule": "specific behaviour rule", "fixes": "what problem this fixes"}}
    ],
    "rules_to_strengthen": ["existing rule text to reinforce"],
    "biggest_opportunity": "the single most impactful change",
    "quality_trend": "improving/stable/declining"
}}"""

        synthesis = await gemini_json(prompt, task="reasoning", max_tokens=1024)

        if synthesis:
            # Write new rules to DB
            conn = get_conn()
            cur = conn.cursor()
            for rule_item in synthesis.get("new_rules", [])[:3]:
                rule_text = rule_item.get("rule", "")
                if rule_text and len(rule_text) > 10:
                    cur.execute("""
                        INSERT INTO tony_behaviour_rules (rule_type, rule_text, confidence, source)
                        VALUES ('learned', %s, 0.7, 'weekly_synthesis')
                        ON CONFLICT (rule_text) DO UPDATE SET
                            confidence = LEAST(1.0, tony_behaviour_rules.confidence + 0.1),
                            evidence_count = tony_behaviour_rules.evidence_count + 1,
                            updated_at = NOW()
                    """, (rule_text[:300],))

            # Strengthen existing rules
            for rule_text in synthesis.get("rules_to_strengthen", [])[:2]:
                cur.execute("""
                    UPDATE tony_behaviour_rules
                    SET confidence = LEAST(1.0, confidence + 0.05),
                        evidence_count = evidence_count + 1
                    WHERE rule_text ILIKE %s
                """, (f"%{rule_text[:30]}%",))

            conn.commit()
            cur.close()
            conn.close()

            print(f"[LEARNING] Weekly synthesis: {len(synthesis.get('new_rules', []))} new rules. Trend: {synthesis.get('quality_trend', 'unknown')}")
            return {"synthesised": True, "synthesis": synthesis}

    except Exception as e:
        print(f"[LEARNING] Weekly synthesis failed: {e}")
        return {"synthesised": False, "error": str(e)}
