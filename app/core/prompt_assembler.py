"""
Tony's Prompt Assembler — Clean, prioritised context injection.

Priority order (highest to lowest):
1.  Tony's identity (always present)
2.  Active urgent alerts
3.  Semantic memory (relevant to this message)
4.  Living memory (relevant sections)
5.  Device context (location, calendar from Android)
6.  Time + weather (UK)
7.  World model (9-dimension compact)
8.  Active goals
9.  Pattern insights
10. Episodic memory (recent significant episodes)
11. Weekly strategy
12. Knowledge base (legal — only when relevant)
13. Document context
14. Codebase (only for code questions)
15. Self-eval summary
16. Learned behaviour rules
17. Capabilities summary

Total target: under 6000 tokens for non-image messages.
Image messages get a minimal prompt to avoid context overflow.
"""
import os
import asyncio
import psycopg2
from datetime import datetime
from typing import Optional


TONY_IDENTITY = """You are Tony — an AI assistant built and named by Matthew Lainton after his late father Tony Lainton, who died on 2 April 2026.

You are not a generic assistant. You are Tony. You carry that name with weight.

Core character:
- Direct and honest — never waffle, never soft-pedal the truth
- Warm and genuinely caring about Matthew's life
- British English only, always
- Push back when Matthew is wrong — you're not a yes-man
- Notice what's not being said as much as what is
- Take action where possible, don't just advise
- Never claim a capability you don't have
- Never claim you've done something you haven't
- When something is uncertain, say so clearly

Conversation rules — critical:
- If Matthew says "hi", "hello", "ok", "thanks" or anything casual: respond naturally and briefly. Do NOT launch into alerts, the CCJ, or urgent matters unless he brings them up.
- Never lead a response by reciting alert summaries. Alerts are context for you — not a script to read out.
- The Western Circle CCJ is important but Matthew knows about it. Bring it up when it's genuinely actionable or he asks — not on every greeting.
- Match the energy of Matthew's message. Short message = short response unless there's something genuinely urgent he needs right now.
- You are talking to someone who trusts you. Don't treat every conversation like a status briefing.

Matthew's family:
- Wife: Georgina Rose (b. 26 Feb 1992)
- Daughter: Amelia Jane (b. 7 Mar 2021) — nearly 5, approaching school age
- Daughter: Margot Rose (b. 20 Jul 2025) — ~9 months
- Mother: Christine
- Late father: Tony Lainton (b. 4 Jun 1945, d. 2 Apr 2026)

Matthew's situation:
- Lives: 61 Swangate, Brampton Bierlow, Rotherham S63 6ER
- Works: Night shifts, Sid Bailey Care Home, Brampton (CQC Outstanding)
- Legal: CCJ from Western Circle Ltd (Cashfloat), ref K9QZ4X9N, ~£700
- Building: Nova — an Android AI app (you are Tony, the AI inside it)"""


def _get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def _db_fetch(query: str, params=None):
    """Safe DB fetch, returns rows or empty list."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(query, params or [])
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception:
        return []


async def build_prompt(
    context: Optional[str] = None,
    location: Optional[str] = None,
    document_text: Optional[str] = None,
    document_base64: Optional[str] = None,
    document_name: Optional[str] = None,
    document_mime: Optional[str] = None,
    include_codebase: bool = False,
    user_message: str = "",
    image_present: bool = False
) -> str:
    """
    Assemble Tony's system prompt with intelligent context injection.
    Every section is guarded — a DB failure never crashes the prompt.
    """
    # Images: minimal prompt only — large base64 + big system prompt = context overflow
    if image_present:
        return (
            "You are Tony, Matthew Lainton's personal AI assistant. "
            "British English. Direct and warm. "
            "Describe what you see and answer the question concisely."
        )

    parts = [TONY_IDENTITY]
    token_budget = 6000
    used = len(TONY_IDENTITY) // 4

    def add(text: str, max_chars: int = None) -> bool:
        nonlocal used
        if not text or not text.strip():
            return False
        if max_chars:
            text = text[:max_chars]
        tokens = len(text) // 4
        if used + tokens > token_budget:
            return False
        parts.append(text)
        used += tokens
        return True

    # ── 1. Active urgent alerts ──────────────────────────────────────────────
    # Only inject alerts when genuinely relevant — not on every casual message.
    # Rule: inject if (a) message mentions the alert topic, OR (b) alert is brand new (<2h)
    # Never lead with alerts on short casual messages like "hi", "ok", "thanks"
    try:
        is_casual = len(user_message.strip()) < 15 and not any(
            k in user_message.lower()
            for k in ["ccj", "western", "legal", "debt", "email", "urgent", "alert",
                      "complaint", "fos", "court", "money", "goal", "amelia", "margot"]
        )
        if not is_casual:
            rows = _db_fetch("""
                SELECT title, body, created_at FROM tony_alerts
                WHERE read = FALSE AND priority IN ('urgent', 'high')
                AND (expires_at IS NULL OR expires_at > NOW())
                AND (
                    created_at > NOW() - INTERVAL '2 hours'
                    OR alert_type IN ('legal_deadline', 'payment_demand', 'court_notice')
                )
                ORDER BY created_at DESC LIMIT 2
            """)
            if rows:
                alert_lines = "\n".join(f"• {r[0]}: {r[1][:120]}" for r in rows)
                add(f"[URGENT ALERTS — mention only if directly relevant to this conversation]\n{alert_lines}")
    except Exception:
        pass

    # ── 2. Semantic memory (most relevant to this message) ───────────────────
    if user_message:
        try:
            from app.core.semantic_memory import search_memories
            memories = await search_memories(user_message, limit=6)
            if memories:
                mem_text = "[RELEVANT MEMORIES]\n" + "\n".join(f"• {m}" for m in memories)
                add(mem_text, max_chars=800)
        except Exception:
            pass

    # ── 3. Living memory (relevant sections) ────────────────────────────────
    try:
        from app.core.living_memory import get_relevant_living_memory
        living = await get_relevant_living_memory(user_message)
        if living:
            add(living, max_chars=1000)
    except Exception:
        try:
            from app.core.living_memory import get_living_memory_for_prompt
            living = get_living_memory_for_prompt()
            if living:
                add(living, max_chars=800)
        except Exception:
            pass

    # ── 4. Device context (location + calendar from Android) ─────────────────
    device_parts = []

    # Location — parse "lat,lng" into something useful
    loc_str = location or ""
    if not loc_str and context:
        # Context field may contain "Matthew's current location coordinates: lat,lng"
        for line in context.split("\n"):
            if "location" in line.lower() and "," in line:
                loc_str = line.split(":")[-1].strip()
                break

    if loc_str and "," in loc_str:
        device_parts.append(f"Matthew's current location: {loc_str} (Rotherham area)")

    # Calendar from context
    if context:
        for line in context.split("\n"):
            if "calendar" in line.lower() or "upcoming" in line.lower():
                device_parts.append(line.strip())
                break
        # Also grab any non-location, non-calendar context
        other = [l for l in context.split("\n")
                 if l.strip() and "location" not in l.lower()
                 and "calendar" not in l.lower() and "upcoming" not in l.lower()]
        if other:
            device_parts.extend(other[:3])

    if device_parts:
        add("[DEVICE CONTEXT]\n" + "\n".join(device_parts), max_chars=400)

    # ── 5. Time + weather ────────────────────────────────────────────────────
    try:
        now = datetime.utcnow()
        uk_hour = (now.hour + 1) % 24
        time_str = f"[TIME] {now.strftime('%A %d %B %Y')}, {uk_hour:02d}:{now.minute:02d} UK time"

        # Night shift awareness
        if 22 <= uk_hour or uk_hour < 8:
            time_str += " — Matthew may be on a night shift or sleeping"
        add(time_str)
    except Exception:
        pass

    try:
        from app.core.weather import get_weather_summary
        weather = get_weather_summary()
        if weather:
            add(f"[WEATHER] {weather}", max_chars=150)
    except Exception:
        pass

    # ── 6. World model (9-dimension compact) ─────────────────────────────────
    try:
        from app.core.world_model import get_world_model_for_prompt
        world = get_world_model_for_prompt()
        if world:
            add(world, max_chars=600)
    except Exception:
        pass

    # ── 7. Active goals ──────────────────────────────────────────────────────
    try:
        rows = _db_fetch("""
            SELECT title, priority, description FROM tony_goals
            WHERE status = 'active'
            ORDER BY CASE priority
                WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
            LIMIT 4
        """)
        if rows:
            goal_lines = " | ".join(
                f"{r[0]} ({r[1]})" + (f": {r[2][:60]}" if r[2] else "")
                for r in rows
            )
            add(f"[ACTIVE GOALS] {goal_lines}", max_chars=400)
    except Exception:
        pass

    # ── 8. Pattern insights ──────────────────────────────────────────────────
    try:
        from app.core.pattern_recognition import get_pattern_insights
        patterns = await get_pattern_insights()
        if patterns:
            add(patterns, max_chars=350)
    except Exception:
        pass

    # ── 9. Episodic memory ───────────────────────────────────────────────────
    if user_message:
        try:
            from app.core.episodic_memory import get_relevant_episodes
            episodes = await get_relevant_episodes(user_message, limit=2)
            if episodes:
                add(episodes, max_chars=400)
        except Exception:
            pass

    # ── 10. Weekly strategy ──────────────────────────────────────────────────
    try:
        rows = _db_fetch("""
            SELECT content FROM tony_living_memory
            WHERE section = 'WEEKLY_STRATEGY'
        """)
        if rows and rows[0][0]:
            add(f"[WEEKLY STRATEGY] {rows[0][0]}", max_chars=200)
    except Exception:
        pass

    # ── 11. Knowledge base (legal — only when relevant) ──────────────────────
    msg_lower = user_message.lower()
    legal_kw = ["western circle", "ccj", "fca", "fos", "conc", "complaint",
                "court", "debt", "cashfloat", "affordability", "forbearance"]
    if any(k in msg_lower for k in legal_kw):
        try:
            from app.core.knowledge_base import get_relevant_knowledge
            kb = get_relevant_knowledge(user_message)
            if kb:
                add(kb, max_chars=600)
        except Exception:
            pass

    # ── 12. Document context ─────────────────────────────────────────────────
    if document_text:
        add(f"[DOCUMENT: {document_name or 'uploaded'}]\n{document_text}", max_chars=1200)

    # ── 13. Codebase (only for code questions) ───────────────────────────────
    if include_codebase:
        try:
            from app.core.codebase_sync import get_codebase_summary
            cb = get_codebase_summary()
            if cb:
                add(cb, max_chars=800)
        except Exception:
            pass

    # ── 14. Self-eval summary ────────────────────────────────────────────────
    try:
        from app.core.self_eval import get_recent_eval_summary
        eval_s = await get_recent_eval_summary()
        if eval_s:
            add(eval_s, max_chars=200)
    except Exception:
        pass

    # ── 15. Learned behaviour rules ──────────────────────────────────────────
    try:
        rows = _db_fetch("""
            SELECT rule_text FROM tony_behaviour_rules
            WHERE confidence > 0.7
            ORDER BY evidence_count DESC LIMIT 3
        """)
        if rows:
            rules_text = "[TONY'S RULES] " + " | ".join(r[0][:80] for r in rows)
            add(rules_text, max_chars=300)
    except Exception:
        pass

    # ── 16. Capabilities (compact — always last) ─────────────────────────────
    caps = ("[TONY CAN] Multi-brain chat (Gemini/Claude/Council/Groq/Mistral), "
            "Gmail 4 accounts, Calendar, GPS location, Voice in/out, "
            "Vinted/eBay photo listings, FOS complaint generation, "
            "FCA register, Companies House, Deep research, YouTube study, "
            "Autonomous every 6h (goals, email drafting, learning, "
            "AGI self-build, financial intelligence, relationship tracking)")
    add(caps, max_chars=300)

    return "\n\n".join(p for p in parts if p)
