import os
import httpx

BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

SEARCH_TRIGGERS = [
    "what is", "who is", "when is", "where is", "how much", "how many",
    "latest", "current", "today", "news", "price", "weather", "score",
    "results", "recent", "now", "live", "update", "happened", "released",
    "new", "2024", "2025", "2026", "this week", "this month", "this year",
    "who won", "what happened", "tell me about", "find", "search",
    "look up", "check", "is there", "are there", "when did", "how is",
]

def should_search(message: str) -> bool:
    if not BRAVE_API_KEY:
        return False
    lower = message.lower()
    return any(trigger in lower for trigger in SEARCH_TRIGGERS)

async def brave_search(query: str, count: int = 5) -> str:
    if not BRAVE_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": BRAVE_API_KEY
                },
                params={
                    "q": query,
                    "count": count,
                    "search_lang": "en",
                    "country": "GB",
                    "text_decorations": False,
                    "extra_snippets": True
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []
            web_results = data.get("web", {}).get("results", [])
            for r in web_results[:count]:
                title = r.get("title", "")
                url = r.get("url", "")
                description = r.get("description", "")
                extra = r.get("extra_snippets", [])
                snippet = description
                if extra:
                    snippet = description + " " + " ".join(extra[:2])
                results.append(f"- {title}\n  {snippet}\n  Source: {url}")

            if not results:
                return ""

            return "LIVE WEB SEARCH RESULTS:\n" + "\n\n".join(results)

    except Exception as e:
        print(f"[BRAVE] search failed: {e}")
        return ""
