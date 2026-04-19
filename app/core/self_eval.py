"""
Tony's Self-Evaluation Engine.

After every conversation, Tony evaluates his own performance.
He asks himself honest questions and logs the results.

This feeds into:
1. The learning engine (what to improve)
2. The meta-cognition engine (patterns in failures)  
3. The autonomous improvement loop (what to build next)

Tony is brutally honest with himself.
If he gave a bad response, he says so.
If he missed something obvious, he notes it.
"""
import os
import psycopg2
from datetime import datetime
from typing import Optional
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_eval_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_eval_log (
                id SERIAL PRIMARY KEY,
                message TEXT,
                reply TEXT,
                provider TEXT,
                score FLOAT,
                what_went_well TEXT,
                what_went_wrong TEXT,
                missed_opportunity TEXT,
                would_do_differently TEXT,
                success BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[SELF_EVAL] Tables initialised")
    except Exception as e:
        print(f"[SELF_EVAL] Init failed: {e}")


async def evaluate_response(
    message: str,
    reply: str,
    provider: str = "gemini"
) -> Optional[dict]:
    """Tony evaluates his own response honestly."""
    prompt = f"""You are Tony evaluating your own response. Be completely honest.

Matthew said: {message[:200]}
You replied: {reply[:300]}

Evaluate yourself on:
1. Did you actually answer what he asked? (not just adjacent to it)
2. Were you genuinely useful or performatively helpful?
3. Did you use your context (memory, calendar, etc) appropriately?
4. Was your tone right — direct and warm, not generic?
5. Did you miss anything obvious?
6. What's one thing you'd do differently?

Score yourself 1-10 where:
1-4 = Poor (wrong answer, missed point, no context used)
5-6 = Mediocre (answered but generic, could be much better)
7-8 = Good (useful, contextual, direct)
9-10 = Excellent (proactive, insightful, exactly right)

Respond in JSON:
{{
    "score": 7.5,
    "what_went_well": "one thing done well",
    "what_went_wrong": "main failure or null",
    "missed_opportunity": "something obvious you missed or null",
    "would_do_differently": "specific change for next time or null"
}}"""

    result = await gemini_json(prompt, task="analysis", max_tokens=300, temperature=0.1)
    
    if result:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO tony_eval_log
                (message, reply, provider, score, what_went_well,
                 what_went_wrong, missed_opportunity, would_do_differently, success)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                message[:300], reply[:300], provider,
                result.get("score"),
                result.get("what_went_well", "")[:200],
                result.get("what_went_wrong", "")[:200],
                result.get("missed_opportunity", "")[:200],
                result.get("would_do_differently", "")[:200],
                (result.get("score", 5) or 5) >= 6
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[SELF_EVAL] Log failed: {e}")
    
    return result


async def get_recent_eval_summary() -> str:
    """Get summary of recent self-evaluations for system prompt."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT AVG(score), COUNT(*),
                   STRING_AGG(would_do_differently, ' | ' ORDER BY created_at DESC)
            FROM tony_eval_log
            WHERE created_at > NOW() - INTERVAL '48 hours'
            AND score IS NOT NULL
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row and row[0]:
            avg, count, improvements = row
            if improvements:
                top_improvement = improvements.split(' | ')[0][:100]
                return f"[TONY'S RECENT SELF-EVAL]: Avg score {avg:.1f}/10 over {count} responses. Focus: {top_improvement}"
    except Exception:
        pass
    return ""
