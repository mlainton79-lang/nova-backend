"""
Tony's Prompt Assembler — Clean, prioritised context injection.

Replaces the scattered injection logic in tony.py with a
clean, prioritised assembly pipeline.

Priority order (highest to lowest):
1. Tony's identity (who he is, always present)
2. Matthew's core details (always present, compact)
3. Active alerts (urgent things Tony needs to know now)
4. Relevant memories (semantic search, top 6)
5. Living memory (relevant sections only)
6. Today's calendar + recent patterns
7. Active goals summary
8. Weekly strategy
9. Capabilities (compressed)
10. Knowledge base (only when relevant)
11. Codebase (only for code questions)

Total target: under 5000 tokens for non-image messages.
"""
import os
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


async def build_prompt(
    context: Optional[str] = None,
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
    """
    # For images: minimal prompt to avoid context overflow
    if image_present:
        return "You are Tony, Matthew Lainton's personal AI assistant. British English. Direct and warm. Describe what you see and answer the question."

    parts = [TONY_IDENTITY]
    token_budget = 5000
    used = len(TONY_IDENTITY) // 4  # rough token estimate

    def add_section(text: str, label: str = "") -> bool:
        nonlocal used
        tokens = len(text) // 4
        if used + tokens > token_budget:
            return False
        if text.strip():
            parts.append(text)
            used += tokens
        return True

    # 1. Active alerts (urgent — always check first)
    try:
        conn = __import__('psycopg2').connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT title, body FROM tony_alerts
            WHERE read = FALSE AND priority IN ('urgent', 'high')
            AND created_at > NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC LIMIT 3
        """)
        alerts = cur.fetchall()
        cur.close()
        conn.close()
        if alerts:
            alert_text = "[URGENT ALERTS]:\n" + "\n".join(f"• {a[0]}: {a[1][:100]}" for a in alerts)
            add_section(alert_text)
    except Exception:
        pass

    # 2. Semantic memory (relevant to this message)
    if user_message:
        try:
            from app.core.semantic_memory import search_memories
            memories = await search_memories(user_message, limit=6)
            if memories:
                mem_text = "[RELEVANT MEMORIES]:\n" + "\n".join(f"• {m}" for m in memories)
                add_section(mem_text)
        except Exception:
            pass

    # 3. Living memory (relevant sections)
    try:
        from app.core.living_memory import get_relevant_living_memory
        living = await get_relevant_living_memory(user_message)
        if living:
            add_section(living)
    except Exception:
        try:
            from app.core.living_memory import get_living_memory_for_prompt
            living = get_living_memory_for_prompt()
            if living:
                add_section(living[:800])
        except Exception:
            pass

    # 4. Today's context (time, calendar)
    try:
        from datetime import datetime
        now = datetime.utcnow()
        uk_hour = (now.hour + 1) % 24
        time_str = f"[TIME]: {now.strftime('%A %d %B %Y')}, {uk_hour:02d}:{now.minute:02d} UK time"
        add_section(time_str)
    except Exception:
        pass

    # 5. Active goals (compact)
    try:
        conn = __import__('psycopg2').connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT title, priority FROM tony_goals
            WHERE status = 'active'
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
            LIMIT 4
        """)
        goals = cur.fetchall()
        cur.close()
        conn.close()
        if goals:
            goals_text = "[ACTIVE GOALS]: " + " | ".join(f"{g[0]} ({g[1]})" for g in goals)
            add_section(goals_text)
    except Exception:
        pass

    # 6. Capabilities (compact)
    caps = "[TONY CAN]: Multi-brain chat (Gemini/Claude/Council), Gmail 4 accounts, Calendar, GPS, Voice, Vinted/eBay listings, FOS complaint generation, FCA register, Companies House, autonomous every 6h (goals, email scan, learning, AGI self-build loop, financial intelligence, relationship tracking)"
    add_section(caps)

    # 7. Pattern insights (if high confidence)
    try:
        from app.core.pattern_recognition import get_pattern_insights
        patterns = await get_pattern_insights()
        if patterns:
            add_section(patterns[:400])
    except Exception:
        pass

    # 7b. World model (compact — always include)
    try:
        from app.core.world_model import get_world_model_for_prompt
        world = get_world_model_for_prompt()
        if world:
            add_section(world[:600])
    except Exception:
        pass

    # 7c. Episodic memory (recent significant episodes)
    if user_message:
        try:
            from app.core.episodic_memory import get_relevant_episodes
            episodes = await get_relevant_episodes(user_message, limit=2)
            if episodes:
                add_section(episodes[:400])
        except Exception:
            pass

    # 8. Weekly strategy (if exists)
    try:
        conn = __import__('psycopg2').connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT content FROM tony_living_memory WHERE section = 'WEEKLY_STRATEGY'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            add_section(f"[WEEKLY STRATEGY]: {row[0][:200]}")
    except Exception:
        pass

    # 9. Knowledge base (only when relevant)
    msg_lower = user_message.lower()
    legal_kw = ["western circle", "ccj", "fca", "fos", "conc", "complaint", "court", "debt"]
    if any(k in msg_lower for k in legal_kw):
        try:
            from app.core.knowledge_base import get_relevant_knowledge
            kb = get_relevant_knowledge(user_message)
            if kb:
                add_section(kb[:600])
        except Exception:
            pass

    # 10. Document context
    if document_text:
        add_section(f"[DOCUMENT: {document_name or 'uploaded'}]:\n{document_text[:1000]}")

    # 11. Codebase (only for code questions)
    if include_codebase:
        try:
            from app.core.codebase_sync import get_codebase_summary
            cb = get_codebase_summary()
            if cb:
                add_section(cb[:800])
        except Exception:
            pass

    # 12. Learned behaviour rules
    try:
        conn = __import__('psycopg2').connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT rule_text FROM tony_behaviour_rules
            WHERE confidence > 0.7
            ORDER BY evidence_count DESC LIMIT 3
        """)
        rules = cur.fetchall()
        cur.close()
        conn.close()
        if rules:
            rules_text = "[TONY'S LEARNED RULES]: " + " | ".join(r[0][:80] for r in rules)
            add_section(rules_text)
    except Exception:
        pass

    return "\n\n".join(p for p in parts if p)
