def format_self_knowledge_block() -> str:
    try:
        import psycopg2
        import os
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("SELECT category, content FROM self_knowledge ORDER BY category")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return ""
        lines = ["TONY'S SELF-KNOWLEDGE:"]
        for row in rows:
            lines.append(f"- [{row[0]}] {row[1]}")
        return "\n".join(lines)
    except Exception:
        return ""
