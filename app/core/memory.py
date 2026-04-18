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
