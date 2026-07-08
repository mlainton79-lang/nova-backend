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

from app.observability import record_run_event, EventSeverity, EVENT_TYPES


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


SUBJECT_NORMALISE = {"user", "i", "me", "myself"}


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

        # One-shot idempotent backfill: remap rows whose subject got recorded
        # as "User" / "I" / "me" / "myself" (a historical LLM-extraction
        # artefact) to "Matthew", matching the forward-looking normaliser
        # in save_facts. On first deploy this rescues the orphaned rows;
        # on every subsequent deploy the WHERE clause matches nothing and
        # both statements no-op.
        placeholder = tuple(SUBJECT_NORMALISE)
        cur.execute("""
            DELETE FROM tony_facts
            WHERE LOWER(subject) IN %s
              AND EXISTS (
                  SELECT 1 FROM tony_facts t2
                  WHERE t2.subject = 'Matthew'
                    AND t2.predicate = tony_facts.predicate
                    AND t2.object = tony_facts.object
              )
            RETURNING id
        """, (placeholder,))
        dropped = cur.fetchall()
        cur.execute("""
            UPDATE tony_facts
            SET subject = 'Matthew'
            WHERE LOWER(subject) IN %s
            RETURNING id
        """, (placeholder,))
        renamed = cur.fetchall()
        print(
            f"[FACTS] Subject migration: renamed {len(renamed)} "
            f"User/I/me/myself-subject facts to Matthew; "
            f"dropped {len(dropped)} duplicates"
        )

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

Return STRICT JSON: an array of {{subject, predicate, object, confidence}}.

Subject should be "Matthew" or a specific person/thing.
Predicate should be a short verb phrase.
Object is the value.
Confidence: 0.5 (weak), 0.7 (clear), 0.9 (certain).

Examples of GOOD facts:
  {{"subject": "Matthew", "predicate": "daughter is named", "object": "Amelia Jane", "confidence": 0.9}}
  {{"subject": "Matthew", "predicate": "works at", "object": "Sid Bailey Care Home", "confidence": 0.9}}
  {{"subject": "Georgina", "predicate": "birthday", "object": "26 Feb", "confidence": 0.9}}

Examples of BAD facts (skip):
  Current emotion, weather, time-of-day state, conversational filler

Conversation turn:
User: "{user_message}"
Tony: "{assistant_reply}"

If no fact-worthy content, return: []

Respond with JSON array only, no prose:"""


async def extract_facts_from_text(text: str, max_facts: int = 10) -> List[Dict]:
    """Extract atomic fact triples from a single block of text.

    Sibling to `extract_facts` (which is conversation-shaped — User/Tony
    turns) for use cases where the input is unstructured: a web page
    body, an email body, prior-step results, etc. Same return shape
    `[{subject, predicate, object, confidence}, ...]` so downstream
    callers (memory_save dispatcher, save_facts) can consume either
    interchangeably.

    Routed through `model_router.gemini_json` with `disable_thinking=True`
    — the JSON-array shape is trivial enough that flash's thinking-mode
    just burns output budget and returns empty (proven by 2026-06-02
    litmus where the direct gemini_client path returned [] even on a
    six-fact description). disable_thinking is the same pattern as
    gmail_send / calendar_write / vinted_draft_review use.
    """
    if not text or not text.strip():
        return []
    try:
        from app.core.model_router_smart import is_provider_skipped
        if is_provider_skipped("gemini"):
            return []
    except Exception:
        pass

    prompt = (
        "Extract atomic facts from the text below. A fact is a triple: "
        "(subject, predicate, object).\n\n"
        "ONLY extract facts that are:\n"
        "- Explicitly stated in the text (not inferred, not assumed)\n"
        "- Concrete and self-contained (would still make sense out of context)\n"
        "- NOT trivial (don't extract things like 'the page has a title')\n\n"
        "Return STRICT JSON: an object with a `facts` array of "
        '{"subject", "predicate", "object", "confidence"}. '
        f"At most {max_facts} facts.\n\n"
        "Subject is the entity the fact is about (a person, place, thing, concept).\n"
        "Predicate is a short verb phrase.\n"
        "Object is the value (string).\n"
        "Confidence: 0.5 (weak/possibly inferred), 0.7 (clear), 0.9 (certain).\n\n"
        "Text:\n"
        f'"""\n{text[:6000]}\n"""\n\n'
        "If no fact-worthy content, return facts=[].\n\n"
        'Respond in JSON: {"facts": [...]}'
    )

    try:
        from app.core.model_router import gemini
        import re as _re
        raw = await gemini(
            prompt, task="general", max_tokens=2048,
            disable_thinking=True, temperature=0.1,
        )
        if not raw:
            print(f"[FACTS] extract_facts_from_text: gemini returned empty (text_chars={len(text)})")
            return []
        # Try to parse as either a plain array or a {facts: [...]} object.
        cleaned = _re.sub(r'```json|```', '', raw).strip()
        parsed = None
        try:
            parsed = json.loads(cleaned)
        except Exception:
            arr_match = _re.search(r'\[.*\]', cleaned, _re.DOTALL)
            if arr_match:
                try:
                    parsed = json.loads(arr_match.group())
                except Exception:
                    pass
            if parsed is None:
                obj_match = _re.search(r'\{.*\}', cleaned, _re.DOTALL)
                if obj_match:
                    try:
                        parsed = json.loads(obj_match.group())
                    except Exception:
                        pass
        if parsed is None:
            print(f"[FACTS] extract_facts_from_text: failed to parse JSON. raw[:300]={raw[:300]!r}")
            return []
        if isinstance(parsed, list):
            facts = parsed
        elif isinstance(parsed, dict):
            facts = parsed.get("facts") or []
        else:
            return []
        if not isinstance(facts, list):
            return []
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
        return valid[:max_facts]
    except Exception as e:
        print(f"[FACTS] extract_facts_from_text error: {e}")
        return []


async def extract_facts(user_message: str, assistant_reply: str) -> List[Dict]:
    """Run Gemini extraction on a conversation turn. Returns list of facts."""
    try:
        from app.core.model_router_smart import is_provider_skipped
        if is_provider_skipped("gemini"):
            return []
    except Exception:
        pass

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return []

    prompt = EXTRACTION_PROMPT.format(
        user_message=user_message[:1000],
        assistant_reply=assistant_reply[:1000],
    )

    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": 800, "temperature": 0.1},
            timeout=15.0,
            caller_context="fact_extractor",
        )
        response = gemini_client.extract_text(resp)

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
    # Forward-looking guard: when the extractor is fed a synthesised
    # "User: I ..." payload (e.g. NovaApiClient.addMemory) with no named
    # anchor, Gemini sometimes emits subject="User" despite the prompt's
    # guidance. The read path defaults to subject="Matthew", so those
    # rows get silently orphaned. Normalise any first-person/placeholder
    # subject to "Matthew" before insert.
    for f in facts:
        if str(f.get("subject", "")).strip().lower() in SUBJECT_NORMALISE:
            f["subject"] = "Matthew"
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
                record_run_event(
                    event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
                    severity=EventSeverity.ERROR,
                    subsystem="memory.tony_facts",
                    message="Per-fact INSERT into tony_facts failed inside save_facts loop",
                    error_class=type(e).__name__,
                    error_message=str(e),
                )
        cur.close()
        conn.close()
        return saved
    except Exception as e:
        print(f"[FACTS] Save batch failed: {e}")
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="memory.tony_facts",
            message="save_facts batch failed before per-fact INSERT loop completed",
            error_class=type(e).__name__,
            error_message=str(e),
        )
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
