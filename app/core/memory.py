import os
from datetime import datetime, date
from app.core.logger import get_conn

def add_memory(category: str, text: str):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO memories (category, text) VALUES (%s, %s)",
            (category, text[:1000])
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[MEMORY] add failed: {e}")

    # Also index semantically for relevance-based retrieval
    try:
        import asyncio as _am_asyncio
        from app.core.semantic_memory import add_semantic_memory
        try:
            loop = _am_asyncio.get_event_loop()
            if loop.is_running():
                _am_asyncio.create_task(add_semantic_memory(category, text))
            else:
                loop.run_until_complete(add_semantic_memory(category, text))
        except Exception:
            pass
    except Exception as e:
        print(f"[MEMORY] Semantic index failed: {e}")

def calculate_age(birthdate_str: str) -> str:
    try:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%B %d, %Y"):
            try:
                bd = datetime.strptime(birthdate_str.strip(), fmt).date()
                today = date.today()
                age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
                return str(age)
            except ValueError:
                continue
    except Exception:
        pass
    return ""

def enrich_with_ages(memories: list) -> list:
    enriched = []
    for m in memories:
        text = m.get("text", "")
        if "born" in text.lower() or "birthday" in text.lower():
            import re
            date_pattern = r'\b(\d{1,2}[\s/\-]\w+[\s/\-]\d{2,4}|\w+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})\b'
            matches = re.findall(date_pattern, text)
            for match in matches:
                age = calculate_age(match)
                if age and f"age {age}" not in text:
                    text = text + f" (age {age})"
                    break
        enriched.append({**m, "text": text})
    return enriched

def format_memory_block(memories: list = None) -> str:
    try:
        if memories is None:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, category, text, created_at FROM memories ORDER BY created_at DESC LIMIT 100")
            rows = cur.fetchall()
            cur.close()
            conn.close()
            memories = [{"id": r[0], "category": r[1], "text": r[2], "created_at": str(r[3])} for r in rows]
        if not memories:
            return ""
        enriched = enrich_with_ages(memories)
        lines = ["TONY'S MEMORY OF MATTHEW:"]
        for m in enriched:
            lines.append(f"- [{m.get('category', 'general')}] {m.get('text', '')}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[MEMORY] format failed: {e}")
        return ""


async def deduplicate_memories():
    """
    Remove near-duplicate memories from both tables.
    Runs on startup and as part of the autonomous loop.
    Uses Gemini to identify semantic duplicates.
    """
    import httpx, json, re, os
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        return

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get all memories
        cur.execute("SELECT id, category, text FROM memories ORDER BY created_at DESC LIMIT 200")
        memories = cur.fetchall()
        cur.close()
        conn.close()

        if len(memories) < 2:
            return

        # Group by category for efficiency
        by_category = {}
        for mid, cat, text in memories:
            by_category.setdefault(cat, []).append((mid, text))

        to_delete = set()

        for cat, items in by_category.items():
            if len(items) < 2:
                continue

            # Simple text similarity first — exact duplicates
            seen_texts = {}
            for mid, text in items:
                normalized = text.lower().strip()
                if normalized in seen_texts:
                    to_delete.add(mid)  # Keep first, delete later ones
                else:
                    seen_texts[normalized] = mid

        if to_delete:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM memories WHERE id = ANY(%s)",
                (list(to_delete),)
            )
            conn.commit()
            cur.close()
            conn.close()
            print(f"[MEMORY] Deduplicated: removed {len(to_delete)} exact duplicates")

    except Exception as e:
        print(f"[MEMORY] Dedup failed: {e}")
