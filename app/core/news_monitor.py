"""
Tony's News and Topic Monitor.
Tony watches topics that matter to Matthew and surfaces relevant news.
Uses Brave Search API (already have key).
"""
import os
import httpx
import asyncio
import psycopg2
from datetime import datetime, timedelta

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_news_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_watched_topics (
                id SERIAL PRIMARY KEY,
                topic TEXT NOT NULL,
                keywords TEXT,
                last_checked TIMESTAMP,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_news_items (
                id SERIAL PRIMARY KEY,
                topic TEXT,
                title TEXT,
                url TEXT,
                description TEXT,
                published TEXT,
                seen BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()

        # Seed with Matthew's topics
        topics = [
            ("FCA consumer credit enforcement", "FCA enforcement consumer credit payday loans"),
            ("CCJ removal UK", "CCJ removal set aside consumer rights UK"),
            ("Western Circle Cashfloat", "Western Circle Cashfloat FCA complaints"),
            ("UK cost of living", "UK cost of living energy bills benefits 2026"),
        ]
        for topic, keywords in topics:
            cur.execute("""
                INSERT INTO tony_watched_topics (topic, keywords)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (topic, keywords))
        conn.commit()
        cur.close()
        conn.close()
        print("[NEWS] Tables initialised")
    except Exception as e:
        print(f"[NEWS] Init failed: {e}")


async def search_news(query: str, count: int = 5) -> list:
    """Search for news on a topic."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/news/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                params={"q": query, "count": count, "freshness": "pw"}  # past week
            )
            if r.status_code == 200:
                return r.json().get("results", [])
            # Fallback to web search
            r2 = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                params={"q": query, "count": count}
            )
            return r2.json().get("web", {}).get("results", []) if r2.status_code == 200 else []
    except Exception as e:
        print(f"[NEWS] Search failed: {e}")
        return []


async def tony_scan_news() -> list:
    """Tony scans all watched topics for new developments."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, topic, keywords FROM tony_watched_topics WHERE active = TRUE")
        topics = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        return []

    new_items = []
    for topic_id, topic, keywords in topics:
        results = await search_news(keywords or topic, count=3)
        for r in results:
            title = r.get("title", "")
            url = r.get("url", "")
            desc = r.get("description", "")
            if title and url:
                try:
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO tony_news_items (topic, title, url, description)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id
                    """, (topic, title[:200], url[:500], desc[:500]))
                    if cur.fetchone():
                        new_items.append({"topic": topic, "title": title, "url": url})
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    pass

        # Update last checked
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE tony_watched_topics SET last_checked = NOW() WHERE id = %s", (topic_id,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

    return new_items


def add_watched_topic(topic: str, keywords: str = None):
    """Matthew tells Tony to watch a new topic."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_watched_topics (topic, keywords)
            VALUES (%s, %s)
        """, (topic, keywords or topic))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[NEWS] Add topic failed: {e}")
        return False


def get_unseen_news() -> list:
    """Get news items Tony hasn't surfaced yet."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT topic, title, url, description, created_at
            FROM tony_news_items
            WHERE seen = FALSE
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.execute("UPDATE tony_news_items SET seen = TRUE WHERE seen = FALSE")
        conn.commit()
        cur.close()
        conn.close()
        return [{"topic": r[0], "title": r[1], "url": r[2], "description": r[3]} for r in rows]
    except Exception:
        return []
