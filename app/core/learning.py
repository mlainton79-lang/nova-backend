"""
Tony's Continuous Learning Loop.

Tony doesn't just store memories — he learns from outcomes.

After consequential actions, Tony:
1. Records what he did and what the result was
2. Scores his own performance
3. Identifies patterns in what works and what doesn't
4. Updates his approach weights for future similar situations
5. Rewrites his own behaviour rules when patterns are clear

This is the core of self-improvement. Without it, Tony repeats
the same mistakes indefinitely. With it, he gets better at
specifically helping Matthew over time.
"""
import os
import re
import json
import httpx
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_learning_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_learning_log (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                context TEXT,
                action_taken TEXT NOT NULL,
                outcome TEXT,
                score FLOAT,
                lesson TEXT,
                applied BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_behaviour_rules (
                id SERIAL PRIMARY KEY,
                rule_type TEXT NOT NULL,
                rule_text TEXT NOT NULL,
                confidence FLOAT DEFAULT 0.5,
                evidence_count INTEGER DEFAULT 1,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # Seed some initial behaviour rules Tony can refine
        cur.execute("""
            INSERT INTO tony_behaviour_rules (rule_type, rule_text, confidence, evidence_count)
            VALUES
            ('communication', 'Matthew prefers direct answers without preamble', 0.9, 1),
            ('communication', 'Matthew wants British English only', 1.0, 1),
            ('task_approach', 'Verify actions actually worked before claiming success', 0.9, 1),
            ('tone', 'Be warm but direct — like a father, not a servant', 0.9, 1)
            ON CONFLICT DO NOTHING
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[LEARNING] Tables initialised")
    except Exception as e:
        print(f"[LEARNING] Init failed: {e}")


def log_action(action_type: str, context: str, action_taken: str):
    """Log an action Tony took for later evaluation."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_learning_log (action_type, context, action_taken)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (action_type, context[:500], action_taken[:500]))
        log_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return log_id
    except Exception as e:
        print(f"[LEARNING] Log failed: {e}")
        return None


def record_outcome(log_id: int, outcome: str, score: float):
    """Record what actually happened after an action."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_learning_log
            SET outcome = %s, score = %s
            WHERE id = %s
        """, (outcome[:500], score, log_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[LEARNING] Outcome record failed: {e}")


def get_behaviour_rules() -> List[Dict]:
    """Get Tony's current behaviour rules for system prompt injection."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT rule_type, rule_text, confidence
            FROM tony_behaviour_rules
            WHERE active = TRUE AND confidence > 0.6
            ORDER BY confidence DESC
            LIMIT 10
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"type": r[0], "rule": r[1], "confidence": r[2]} for r in rows]
    except Exception as e:
        print(f"[LEARNING] Rules fetch failed: {e}")
        return []


def format_behaviour_rules_for_prompt() -> str:
    """Format Tony's learned behaviour rules for system prompt."""
    rules = get_behaviour_rules()
    if not rules:
        return ""
    lines = ["[LEARNED BEHAVIOUR — apply these]:"]
    for r in rules:
        lines.append(f"- {r['rule']}")
    return "\n".join(lines)


async def analyse_conversation_for_learning(
    message: str, reply: str, provider: str
) -> Optional[Dict]:
    """
    After each conversation, Tony analyses whether he responded well
    and what he could learn from it.
    """
    if not GEMINI_API_KEY:
        return None

    # Only analyse substantial exchanges
    if len(message) < 20 or len(reply) < 50:
        return None

    prompt = f"""You are Tony's self-improvement system. Analyse this conversation exchange.

Matthew said: {message[:400]}
Tony replied: {reply[:400]}

Evaluate Tony's response on these dimensions:
1. Did Tony answer what was actually asked? (0-10)
2. Was the response appropriately concise? (0-10)
3. Did Tony add genuine value beyond the obvious? (0-10)
4. Was the tone right — direct, warm, British? (0-10)
5. Did Tony make any mistakes or miss anything important?

Also: Is there a LESSON here that Tony should remember for future similar situations?

Respond in JSON only:
{{
    "scores": {{"relevance": 0-10, "conciseness": 0-10, "value": 0-10, "tone": 0-10}},
    "overall": 0-10,
    "mistakes": ["any mistakes made"],
    "lesson": "one sentence lesson for future (or null if nothing to learn)",
    "new_rule": "a new behaviour rule Tony should follow (or null)"
}}"""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 512, "temperature": 0.1}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r'```json|```', '', text).strip()
            data = json.loads(text)

            # Store the lesson
            if data.get("lesson"):
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO tony_learning_log
                    (action_type, context, action_taken, score, lesson, outcome)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    "conversation",
                    message[:300],
                    reply[:300],
                    data.get("overall", 5) / 10,
                    data.get("lesson", ""),
                    "analysed"
                ))
                conn.commit()
                cur.close()
                conn.close()

            # Add new behaviour rule if confidence is high
            if data.get("new_rule") and data.get("overall", 0) >= 7:
                conn = get_conn()
                cur = conn.cursor()
                # Check if similar rule exists
                cur.execute(
                    "SELECT id FROM tony_behaviour_rules WHERE rule_text = %s",
                    (data["new_rule"][:300],)
                )
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO tony_behaviour_rules
                        (rule_type, rule_text, confidence, evidence_count)
                        VALUES ('learned', %s, 0.6, 1)
                    """, (data["new_rule"][:300],))
                    conn.commit()
                cur.close()
                conn.close()

            return data

    except Exception as e:
        print(f"[LEARNING] Analysis failed: {e}")
        return None


async def run_weekly_learning_synthesis():
    """
    Tony reviews a week of conversations and synthesises what he's learned.
    Updates behaviour rules based on evidence patterns.
    Runs as part of the autonomous loop.
    """
    if not GEMINI_API_KEY:
        return

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get recent lessons
        cur.execute("""
            SELECT lesson, score, action_type
            FROM tony_learning_log
            WHERE lesson IS NOT NULL
            AND created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
            LIMIT 50
        """)
        lessons = cur.fetchall()

        # Get current rules
        cur.execute("""
            SELECT rule_text, confidence, evidence_count
            FROM tony_behaviour_rules
            WHERE active = TRUE
        """)
        current_rules = cur.fetchall()
        cur.close()
        conn.close()

        if not lessons:
            return

        lessons_text = "\n".join(f"- [{r[1]:.1f}] {r[0]}" for r in lessons if r[0])
        rules_text = "\n".join(f"- {r[0]} (confidence: {r[1]:.1f})" for r in current_rules)

        prompt = f"""Tony is reviewing his last week of conversations with Matthew to improve.

Lessons learned this week:
{lessons_text}

Current behaviour rules:
{rules_text}

Based on the patterns in these lessons:
1. Which existing rules should have higher/lower confidence?
2. Are there new rules that emerge from repeated patterns?
3. What is Tony doing consistently well?
4. What is Tony consistently getting wrong?

Respond in JSON:
{{
    "rule_updates": [{{"rule": "text", "new_confidence": 0.0-1.0}}],
    "new_rules": ["rule text"],
    "strengths": ["what Tony does well"],
    "weaknesses": ["what Tony should fix"]
}}"""

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.2}
                }
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r'```json|```', '', text).strip()
            data = json.loads(text)

        conn = get_conn()
        cur = conn.cursor()

        # Apply rule updates
        for update in data.get("rule_updates", []):
            cur.execute("""
                UPDATE tony_behaviour_rules
                SET confidence = %s, updated_at = NOW(),
                    evidence_count = evidence_count + 1
                WHERE rule_text = %s
            """, (update["new_confidence"], update["rule"]))

        # Add new rules
        for rule in data.get("new_rules", []):
            cur.execute("""
                INSERT INTO tony_behaviour_rules (rule_type, rule_text, confidence)
                VALUES ('synthesised', %s, 0.65)
                ON CONFLICT DO NOTHING
            """, (rule[:300],))

        conn.commit()
        cur.close()
        conn.close()
        print(f"[LEARNING] Weekly synthesis complete. {len(data.get('new_rules', []))} new rules added.")

    except Exception as e:
        print(f"[LEARNING] Weekly synthesis failed: {e}")
