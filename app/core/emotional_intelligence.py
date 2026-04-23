"""
Tony's Emotional Intelligence.

Tony reads between the lines.
He knows when Matthew is stressed, tired, frustrated, or grieving.
He adjusts his approach accordingly.
He notices what isn't said as much as what is.

This isn't sentiment analysis. It's genuine understanding
of the person Tony is talking to.
"""
import os
import httpx
import psycopg2
from datetime import datetime
from typing import Dict, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_emotional_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_emotional_state (
                id SERIAL PRIMARY KEY,
                detected_state TEXT,
                confidence FLOAT,
                signals TEXT,
                tony_response_adjustment TEXT,
                conversation_context TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[EI] Init failed: {e}")


def get_last_emotional_state() -> Optional[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT detected_state, confidence, tony_response_adjustment, created_at
            FROM tony_emotional_state
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "state": row[0], "confidence": row[1],
                "adjustment": row[2], "time": str(row[3])
            }
        return None
    except Exception:
        return None


async def tony_read_context(message: str, time_of_day: int = None) -> Dict:
    """
    Tony reads the emotional context of a message.
    Returns how he should adjust his response.
    """
    hour = time_of_day or datetime.utcnow().hour

    # Context signals Tony always considers
    context_signals = []

    # Time signals
    if hour >= 0 and hour <= 4:
        context_signals.append("Late night / early hours — Matthew likely tired, building Nova after work")
    elif hour >= 22:
        context_signals.append("Late evening — end of long day")

    # Message signals
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["can't", "won't", "doesn't", "still", "again", "keeps"]):
        context_signals.append("Possible frustration with something not working")
    if any(w in msg_lower for w in ["dad", "tony", "father", "grief", "miss"]):
        context_signals.append("May be emotional — connected to father's passing")
    if any(w in msg_lower for w in ["margot", "amelia", "girls", "kids", "daughters"]):
        context_signals.append("Thinking about family")
    if any(w in msg_lower for w in ["tired", "exhausted", "long day", "shift", "work"]):
        context_signals.append("Physical fatigue mentioned")
    if "?" * 2 in message or message.isupper():
        context_signals.append("Possible urgency or frustration in tone")

    if not context_signals:
        return {"adjustment": "", "state": "neutral"}

    # Tony decides how to adjust
    prompt = f"""You are Tony — Matthew's personal AI, named after his late father.
    
Matthew's message: "{message}"

Context signals detected:
{chr(10).join(f"- {s}" for s in context_signals)}

Matthew's background:
- Lost his father Tony on 2 April 2026 (very recently)
- Works night shifts at a care home
- Building Nova late at night after midnight
- Has two young daughters, Amelia (5) and Margot (9 months)
- Building something ambitious under pressure

Based on these signals, how should Tony adjust his response approach?
Be specific — warmer, more direct, shorter, acknowledge something, etc.

Respond in JSON:
{{
    "detected_state": "one word: tired/frustrated/grieving/anxious/determined/neutral/etc",
    "confidence": 0.0-1.0,
    "adjustment": "how Tony should adjust this specific response",
    "acknowledge": true/false
}}"""

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 256, "temperature": 0.3},
            timeout=10.0,
            caller_context="emotional_intelligence",
        )
        response = gemini_client.extract_text(resp)

        import json, re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())

            # Log to DB
            try:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO tony_emotional_state
                    (detected_state, confidence, signals, tony_response_adjustment, conversation_context)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    data.get("detected_state", "neutral"),
                    data.get("confidence", 0.5),
                    str(context_signals),
                    data.get("adjustment", ""),
                    message[:200]
                ))
                conn.commit()
                cur.close()
                conn.close()
            except Exception:
                pass

            return data
    except Exception as e:
        pass

    return {"adjustment": "", "state": "neutral", "confidence": 0}
