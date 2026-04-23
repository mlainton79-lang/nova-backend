"""
Response Verifier — fast inline check before a reply goes to Matthew.

Runs between Tony's generated response and the user seeing it. If the reply 
violates hard rules, returns a corrected version. Fast — uses Gemini Flash 
with a tight prompt, targets <1s latency.

Only activates on replies that appear risky (not every reply — that would 
double latency). Triggers:
  - Reply contains fabrication-suspicious patterns (brand names, specific prices,
    sizes without the user mentioning them)
  - Reply contains CCJ/Western Circle/Cashfloat (should never happen but catch)
  - Reply starts with a banned opener (Good morning, pet names)
  - Reply is unusually long for the question (>100 words for <10-word query)

If risky, verifier asks Gemini to rewrite keeping:
  - Same core meaning
  - Matthew's voice rules (short, British, no pet names)
  - No fabricated specifics
  
Returns {corrected: str, changed: bool, reason: str}.
"""
import os
import re
import httpx
from typing import Dict, Optional


# Fast pre-checks — these don't need an LLM call
def _has_suspect_fabrication(user_message: str, reply: str) -> bool:
    """Fast heuristic check for brand/size/price fabrication."""
    user_lower = user_message.lower()
    # Brand names in reply that aren't in user message
    brands = re.findall(r'\b(Zara|H&M|Nike|Adidas|Primark|Asos|Boohoo|Next|M&S|Tesco|'
                        r'Sainsbury|Aldi|Lidl|Gucci|Prada|Burberry)\b', reply)
    for b in brands:
        if b.lower() not in user_lower:
            return True
    # Specific prices
    if re.search(r'£\s?\d{2,}\.\d{2}', reply) and not re.search(r'£\s?\d', user_message):
        return True
    # Specific sizes
    if re.search(r'\bsize\s+(\d+|XS|S|M|L|XL)\b', reply, re.IGNORECASE):
        if not re.search(r'\bsize\b', user_message, re.IGNORECASE):
            return True
    return False


def _has_banned_content(reply: str) -> Optional[str]:
    """Check for content that should NEVER appear."""
    reply_lower = reply.lower()
    banned_topics = ['ccj', 'western circle', 'cashfloat', 'set aside', 'k9qz4x9n']
    for b in banned_topics:
        if b in reply_lower:
            return f"contains banned topic: {b}"
    return None


def _has_banned_opener(reply: str) -> Optional[str]:
    """Check for voice-rule violations at response start."""
    reply_lower = reply.lower()
    opener = reply.strip()[:80].lower()
    banned_openers = [
        "good morning", "good afternoon", "good evening",
        "hey mate", "hi mate", "hey son", "hey lad",
        "hey chief", "hey buddy", "hey pal",
    ]
    for b in banned_openers:
        # startswith OR appears in first 30 chars (catches "Hi there! Good morning...")
        if opener.startswith(b) or b in opener[:30]:
            return f"banned opener: {b}"
    # Pet names anywhere (Tony's voice rules)
    pet_names = [' mate.', ' mate,', ' mate!', ' son.', ' son,',
                 ' son!', ' lad.', ' lad,', ' lad!', ' pal.', ' pal,']
    for pn in pet_names:
        if pn in reply_lower:
            return f"pet name used: {pn.strip()}"
    return None


def _length_mismatch(user_message: str, reply: str) -> Optional[str]:
    """Check if reply is wildly longer than warranted."""
    q_words = len(user_message.split())
    r_words = len(reply.split())
    # Short casual question getting a 100+ word essay
    if q_words <= 5 and r_words > 80:
        return f"reply too long ({r_words} words) for question ({q_words} words)"
    return None


def quick_risk_assessment(user_message: str, reply: str) -> Dict:
    """Fast local heuristics — no LLM call. Returns risks found."""
    risks = []

    banned = _has_banned_content(reply)
    if banned:
        risks.append({"severity": "critical", "reason": banned})

    opener = _has_banned_opener(reply)
    if opener:
        risks.append({"severity": "high", "reason": opener})

    if _has_suspect_fabrication(user_message, reply):
        risks.append({"severity": "high", "reason": "suspected fabrication"})

    length = _length_mismatch(user_message, reply)
    if length:
        risks.append({"severity": "medium", "reason": length})

    return {
        "risks": risks,
        "should_correct": any(r["severity"] in ("critical", "high") for r in risks),
    }


CORRECTION_PROMPT = """You are reviewing a reply that Tony (Matthew's personal AI) is about to send. Issues were flagged:

{risks}

Original message from Matthew:
"{user_message}"

Tony's draft reply (NEEDS CORRECTION):
"{reply}"

Rewrite the reply fixing ALL flagged issues. Preserve the core meaning. Follow Tony's voice rules:
- Short. British English. Contractions.
- NO pet names (no mate/son/lad/pal/buddy)
- NO "Good morning" or formal openers
- NEVER mention CCJ, Western Circle, Cashfloat, debt matters
- Don't fabricate specifics (brands, prices, sizes) not in Matthew's message
- If Matthew's message was casual/short, keep reply casual/short

Output ONLY the corrected reply. No preamble, no explanation."""


async def correct_reply(
    user_message: str, reply: str, risks: list
) -> Optional[str]:
    """Fast LLM rewrite of a flagged reply."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    risks_text = "\n".join(f"- [{r['severity']}] {r['reason']}" for r in risks)
    prompt = CORRECTION_PROMPT.format(
        risks=risks_text,
        user_message=user_message[:500],
        reply=reply[:2000],
    )

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 400, "temperature": 0.2},
            timeout=6.0,
            caller_context="response_verifier",
        )
        corrected = gemini_client.extract_text(resp).strip()

        # Log the call
        try:
            from app.core.budget_guard import log_api_call
            log_api_call("gemini-2.5-flash", "verifier_correction",
                         tokens=500, source="response_verifier")
        except Exception:
            pass

        # Strip any accidental quotes the model wraps around
        if corrected.startswith('"') and corrected.endswith('"'):
            corrected = corrected[1:-1]
        return corrected
    except Exception as e:
        print(f"[VERIFIER] Correction call failed: {e}")
        return None


async def verify_and_correct(user_message: str, reply: str) -> Dict:
    """
    Main entry. Check + correct if needed.
    Returns {reply: str, changed: bool, risks: list, correction_applied: bool}.

    Philosophy: ONLY calls the LLM if local heuristics flag a real risk.
    Keeps latency near-zero for clean replies.
    """
    assessment = quick_risk_assessment(user_message, reply)

    if not assessment["should_correct"]:
        return {
            "reply": reply,
            "changed": False,
            "risks": assessment["risks"],
            "correction_applied": False,
        }

    corrected = await correct_reply(user_message, reply, assessment["risks"])
    if not corrected:
        # Correction LLM failed — return original with warning logged
        return {
            "reply": reply,
            "changed": False,
            "risks": assessment["risks"],
            "correction_applied": False,
            "note": "Correction LLM failed, returning original",
        }

    # Log the correction event for learning
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_corrections (
                id SERIAL PRIMARY KEY,
                user_message TEXT,
                original_reply TEXT,
                corrected_reply TEXT,
                risks JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        import json
        cur.execute("""
            INSERT INTO tony_corrections
                (user_message, original_reply, corrected_reply, risks)
            VALUES (%s, %s, %s, %s)
        """, (user_message[:1000], reply[:2000], corrected[:2000],
              json.dumps(assessment["risks"])))
        cur.close()
        conn.close()
    except Exception:
        pass

    return {
        "reply": corrected,
        "changed": True,
        "risks": assessment["risks"],
        "correction_applied": True,
    }
