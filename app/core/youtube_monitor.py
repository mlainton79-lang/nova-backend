"""
Tony's YouTube Trend Monitor.

Monitors YouTube trends relevant to:
- Resale/Vinted items (what's trending = what sells)
- Care home / healthcare content
- AI and technology developments
- Anything Matthew is interested in

Uses yt-dlp (already in requirements) to fetch trending data
without needing a YouTube API key.
"""
import os
import asyncio
import json
import psycopg2
from datetime import datetime
from typing import List, Dict, Optional
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_youtube_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_youtube_trends (
                id SERIAL PRIMARY KEY,
                category TEXT,
                title TEXT,
                channel TEXT,
                views TEXT,
                url TEXT,
                relevance_score FLOAT DEFAULT 0,
                insight TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[YOUTUBE] Tables initialised")
    except Exception as e:
        print(f"[YOUTUBE] Init failed: {e}")


async def get_trending_videos(category: str = "resale") -> List[Dict]:
    """Get trending YouTube videos for a category using yt-dlp."""
    search_queries = {
        "resale": "what to sell on vinted ebay 2026 trending",
        "care_home": "UK care home 2026 CQC",
        "ai_tech": "AI assistant 2026 latest",
        "finance": "UK money saving 2026 cost of living"
    }

    query = search_queries.get(category, category)

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            f"ytsearch5:{query}",
            "--dump-json",
            "--no-download",
            "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        videos = []
        for line in stdout.decode().strip().split('\n'):
            if line.strip():
                try:
                    data = json.loads(line)
                    videos.append({
                        "title": data.get("title", ""),
                        "channel": data.get("uploader", ""),
                        "views": data.get("view_count", 0),
                        "url": data.get("webpage_url", ""),
                        "duration": data.get("duration", 0),
                        "upload_date": data.get("upload_date", "")
                    })
                except Exception:
                    pass

        return videos

    except asyncio.TimeoutError:
        print(f"[YOUTUBE] Search timed out for: {query}")
        return []
    except Exception as e:
        print(f"[YOUTUBE] Search failed: {e}")
        return []


async def analyse_trends_for_vinted(videos: List[Dict]) -> Optional[str]:
    """Use AI to extract resale insights from trending videos."""
    if not videos:
        return None

    videos_text = "\n".join(
        f"- {v['title']} ({v['views']:,} views)" if isinstance(v['views'], int)
        else f"- {v['title']}"
        for v in videos[:5]
    )

    prompt = f"""Tony is looking at trending YouTube videos about selling/resale to help Matthew on Vinted/eBay.

Trending videos:
{videos_text}

Extract 2-3 specific, actionable insights for Matthew:
- What items are trending for resale right now?
- What categories are getting high views (= high demand)?
- Any specific brands or products mentioned repeatedly?

Keep it brief and practical. These insights will help Matthew know what to source and sell.

Respond in JSON:
{{
    "insights": ["specific insight 1", "insight 2"],
    "trending_items": ["item or category worth selling"],
    "summary": "one sentence summary for Tony to tell Matthew"
}}"""

    return await gemini_json(prompt, task="analysis", max_tokens=512)


async def run_youtube_monitoring() -> Dict:
    """Full YouTube monitoring run."""
    results = {"ok": False, "insights": []}

    try:
        # Focus on resale trends - most useful for Matthew right now
        videos = await get_trending_videos("resale")

        if videos:
            analysis = await analyse_trends_for_vinted(videos)

            if analysis:
                # Store insight as alert if actionable
                if analysis.get("summary"):
                    try:
                        from app.core.proactive import create_alert
                        create_alert(
                            alert_type="youtube_trend",
                            title="Vinted/eBay trend insight",
                            body=analysis.get("summary", ""),
                            priority="normal",
                            source="youtube_monitor"
                        )
                    except Exception:
                        pass

                # Store in DB
                conn = get_conn()
                cur = conn.cursor()
                for video in videos[:3]:
                    cur.execute("""
                        INSERT INTO tony_youtube_trends
                        (category, title, channel, views, url, insight)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        "resale",
                        video.get("title", "")[:200],
                        video.get("channel", "")[:100],
                        str(video.get("views", "")),
                        video.get("url", "")[:300],
                        analysis.get("summary", "")[:300]
                    ))
                conn.commit()
                cur.close()
                conn.close()

                results["ok"] = True
                results["insights"] = analysis.get("insights", [])
                results["summary"] = analysis.get("summary", "")

    except Exception as e:
        print(f"[YOUTUBE] Monitoring failed: {e}")
        results["error"] = str(e)

    return results
