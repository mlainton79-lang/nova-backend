"""
Mem0-style fact extraction.

After each conversation turn, extract atomic facts that should persist long-term.
Uses Gemini to extract, then stores them in tony_facts with:
  - subject (who/what it's about)
  - predicate (the relationship)
  - object (the value)
  - confidence (0-1)
  - source ("conversation" / "email" / "document")
  - extracted_at
  - last_confirmed_at (updated when the same fact is re-extracted)

This gives Tony structured, queryable memory on top of the existing freeform
semantic memory. Both systems complement each other.
"""
import os
import json
import httpx
import psycopg2
from typing import List, Dict, Optional
from datetime import datetime


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_fact_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_facts (
                id SERIAL PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence FLOAT DEFAULT 0.7,
                source TEXT,
                extracted_at TIMESTAMP DEFAULT NOW(),
                last_confirmed_at TIMESTAMP DEFAULT NOW(),
                confirmation_count INT DEFAULT 1,
                superseded_by INT REFERENCES tony_facts(id),
                UNIQUE(subject, predicate, object)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_subject
            ON tony_facts(subject) WHERE superseded_by IS NULL
        """)
        cur.close()
        conn.close()
        print("[FACTS] Tables initialised")
    except Exception as e:
        print(f"[FACTS] Init failed: {e}")


EXTRACTION_PROMPT = """Extract atomic facts from this conversation turn. A fact is a triple: (subject, predicate, object).

ONLY extract facts that:
- Are explicitly stated (not inferred, not guessed)
- Are about Matthew, his family, his work, his preferences, or ongoing situations
- Would be useful to remember long-term
- Are NOT emotional state ("feeling tired"), NOT temporary ("at the shops"), NOT trivial

Return STRICT JSON: an array of {subject, predicate, object, confidence}.

Subject should be "Matthew" or a specific person/thing.
Predicate should be a short verb phrase.
Object is the value.
Confidence: 0.5 (weak), 0.7 (clear), 0.9 (certain).

Examples of GOOD facts:
  {"subject": "Matthew", "predicate": "daughter is named", "object": "Amelia Jane", "confidence": 0.9}
  {"subject": "Matthew", "predicate": "works at", "object": "Sid Bailey Care Home", "confidence": 0.9}
  {"subject": "Georgina", "predicate": "birthday", "object": "26 Feb", "confidence": 0.9}

Examples of BAD facts (skip):
  Current emotion, weather, time-of-day state, conversational filler

Conversation turn:
User: "{user_message}"
Tony: "{assistant_reply}"

If no fact-worthy content, return: []

Respond with JSON array only, no prose:"""


async def extract_facts(user_message: str, assistant_reply: str) -> List[Dict]:
    """Run Gemini extraction on a conversation turn. Returns list of facts."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return []

    prompt = EXTRACTION_PROMPT.format(
        user_message=user_message[:1000],
        assistant_reply=assistant_reply[:1000],
    )

    try:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 800, "temperature": 0.1}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"]

        # Clean markdown fences
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()

        # Find array
        first = cleaned.find("[")
        last = cleaned.rfind("]")
        if first < 0 or last < 0:
            return []

        facts = json.loads(cleaned[first:last+1])
        # Validate structure
        valid = []
        for f in facts:
            if not isinstance(f, dict):
                continue
            if all(k in f for k in ("subject", "predicate", "object")):
                valid.append({
                    "subject": str(f["subject"])[:100],
                    "predicate": str(f["predicate"])[:100],
                    "object": str(f["object"])[:500],
                    "confidence": float(f.get("confidence", 0.7)),
                })
        return valid
    except Exception as e:
        print(f"[FACTS] Extraction error: {e}")
        return []


def save_facts(facts: List[Dict], source: str = "conversation"):
    """Save extracted facts to DB with deduplication via ON CONFLICT."""
    if not facts:
        return 0
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        saved = 0
        for f in facts:
            try:
                cur.execute("""
                    INSERT INTO tony_facts (subject, predicate, object, confidence, source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (subject, predicate, object) DO UPDATE SET
                        last_confirmed_at = NOW(),
                        confirmation_count = tony_facts.confirmation_count + 1,
                        confidence = GREATEST(tony_facts.confidence, EXCLUDED.confidence)
                """, (f["subject"], f["predicate"], f["object"], f["confidence"], source))
                saved += 1
            except Exception as e:
                print(f"[FACTS] Save error for {f}: {e}")
        cur.close()
        conn.close()
        return saved
    except Exception as e:
        print(f"[FACTS] Save batch failed: {e}")
        return 0


def get_facts_about(subject: str, limit: int = 20) -> List[Dict]:
    """Retrieve facts about a specific subject."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, subject, predicate, object, confidence,
                   confirmation_count, last_confirmed_at
            FROM tony_facts
            WHERE LOWER(subject) = LOWER(%s)
              AND superseded_by IS NULL
            ORDER BY confidence DESC, confirmation_count DESC
            LIMIT %s
        """, (subject, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "subject": r[1], "predicate": r[2], "object": r[3],
             "confidence": r[4], "confirmation_count": r[5],
             "last_confirmed_at": str(r[6])}
            for r in rows
        ]
    except Exception:
        return []


def format_facts_for_prompt(subject: str = "Matthew", min_confidence: float = 0.6) -> str:
    """Format stored facts compactly for inclusion in Tony's prompt."""
    facts = get_facts_about(subject)
    facts = [f for f in facts if f["confidence"] >= min_confidence]
    if not facts:
        return ""
    lines = [f"- {f['subject']} {f['predicate']} {f['object']}" for f in facts[:30]]
    return "[KNOWN FACTS]\n" + "\n".join(lines)


async def process_conversation_turn(user_message: str, assistant_reply: str):
    """Main entry: extract + save facts from a conversation turn. Non-blocking."""
    facts = await extract_facts(user_message, assistant_reply)
    if facts:
        saved = save_facts(facts)
        print(f"[FACTS] Extracted {len(facts)} facts, saved {saved}")
    return facts
