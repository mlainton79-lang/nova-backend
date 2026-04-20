"""
Tony's Deep Research Engine.

Tony doesn't just search — he researches.
He reads full pages, follows threads, cross-references sources,
builds a comprehensive understanding of any topic.

This is how Tony develops genuine knowledge, not just search results.
"""
import os
import httpx
import asyncio
import re
from typing import List, Dict

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")


async def fetch_page(url: str) -> str:
    """Fetch and extract readable text from a webpage."""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Tony-AI/1.0)"}
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return ""
            html = r.text
            # Strip HTML tags
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:8000]
    except Exception as e:
        return ""


async def brave_search(query: str, count: int = 10) -> List[Dict]:
    """Search the web via Brave."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                params={"q": query, "count": count}
            )
            results = r.json().get("web", {}).get("results", [])
            return [
                {"title": x.get("title",""), "url": x.get("url",""),
                 "description": x.get("description","")}
                for x in results
            ]
    except Exception as e:
        return []


async def tony_deep_research(topic: str, depth: int = 3) -> Dict:
    """
    Tony researches a topic deeply.
    depth 1 = search results only
    depth 2 = read top 3 pages fully
    depth 3 = read pages + follow key links + synthesise

    Returns a comprehensive research report.
    """
    report = {
        "topic": topic,
        "sources_found": 0,
        "sources_read": 0,
        "findings": "",
        "key_facts": [],
        "sources": []
    }

    # Phase 1: Search
    results = await brave_search(topic, count=10)
    report["sources_found"] = len(results)

    if not results:
        report["findings"] = f"No search results found for: {topic}"
        return report

    # Phase 2: Read pages (depth >= 2)
    pages_content = []
    if depth >= 2:
        # Read top pages concurrently
        top_results = results[:5]
        page_texts = await asyncio.gather(*[
            fetch_page(r["url"]) for r in top_results
        ])

        for i, (result, text) in enumerate(zip(top_results, page_texts)):
            if text and len(text) > 200:
                pages_content.append({
                    "title": result["title"],
                    "url": result["url"],
                    "content": text[:4000]
                })
                report["sources_read"] += 1
                report["sources"].append(result["url"])

    # Phase 3: Synthesise
    search_summary = "\n".join([
        f"- {r['title']}: {r['description']}" for r in results[:8]
    ])

    page_summary = ""
    if pages_content:
        page_summary = "\n\n".join([
            f"FROM: {p['title']} ({p['url']})\n{p['content'][:2000]}"
            for p in pages_content[:3]
        ])

    synthesis_prompt = f"""You are Tony doing deep research for Matthew on: {topic}

SEARCH RESULTS:
{search_summary}

{"FULL PAGE CONTENT READ:" if page_summary else ""}
{page_summary}

Produce a comprehensive research report covering:
1. Key facts and findings
2. Most important information Matthew needs to know
3. Any legal, financial, or practical implications
4. Recommended actions if relevant
5. Most reliable sources

Be specific, precise, and thorough. Matthew is relying on this."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": synthesis_prompt}]}],
                    "generationConfig": {"maxOutputTokens": 4096}
                }
            )
            r.raise_for_status()
            report["findings"] = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        report["findings"] = f"Research synthesis failed: {e}"

    return report


async def tony_research_for_goal(goal_title: str, goal_description: str) -> str:
    """Tony researches specifically to advance one of Matthew's goals."""
    # Identify the best search query for this goal
    query_map = {
        "nova": "best practices agentic AI world model personal assistant 2026",
        "vinted": "Vinted seller tips UK pricing research 2024",
        "ebay": "eBay seller API listing automation Python 2024"
    }

    query = None
    for keyword, search in query_map.items():
        if keyword.lower() in goal_title.lower() or keyword.lower() in goal_description.lower():
            query = search
            break

    if not query:
        query = f"{goal_title} UK advice guide 2024"

    result = await tony_deep_research(query, depth=2)
    return result.get("findings", "No research findings")
