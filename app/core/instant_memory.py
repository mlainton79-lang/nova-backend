"""
Tony's Instant Memory Extraction.

After every message, Tony immediately extracts any new facts
and stores them to memory — no waiting for summarisation.

This catches:
- Facts Matthew mentions in passing ("I'm on nights this week")
- Preferences expressed ("I prefer X to Y")
- Plans mentioned ("I'm going to try selling X")
- Feelings expressed ("I've been stressed about Y")
- Information shared ("My reference number is X")

Instant extraction means Tony never forgets something
that was said, even briefly.
"""
import os
import psycopg2
from typing import List, Optional
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def extract_and_save_instant_memory(
    message: str,
    reply: str
) -> List[str]:
    """
    Extract facts from a message/reply pair and save to memory.
    Fast — uses Flash, not Pro.
    Returns list of facts extracted.
    """
    # Skip very short or non-informative messages
    if len(message) < 15:
        return []

    prompt = f"""Extract specific, memorable facts from this conversation.

Matthew said: {message[:300]}
Tony replied: {reply[:200]}

Extract ONLY facts that Tony should remember long-term.
NOT: questions, general conversation, greetings.
YES: personal details, plans, feelings, preferences, numbers, dates, names.

Examples of good extractions:
- "Matthew prefers Vinted over eBay for clothes"
- "Amelia starts school in September 2026"

Respond with a JSON array of facts (max 3, only real facts):
["fact 1", "fact 2"]

If nothing worth remembering: []"""

    result = await gemini_json(prompt, task="analysis", max_tokens=150, temperature=0.1)

    if not isinstance(result, list):
        return []

    facts = [f for f in result if isinstance(f, str) and len(f) > 10][:3]

    if facts:
        try:
            conn = get_conn()
            cur = conn.cursor()
            for fact in facts:
                cur.execute("""
                    INSERT INTO memories (category, text)
                    VALUES ('auto', %s)
                    ON CONFLICT DO NOTHING
                """, (fact[:500],))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[INSTANT_MEMORY] Save failed: {e}")

    return facts
