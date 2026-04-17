"""
Tony's Agentic Task Engine.

This is the core of Tony's autonomous capability.
When Tony receives a task, he:
1. Breaks it into steps
2. Executes each step using available tools
3. Verifies the result
4. Iterates if something fails
5. Reports back

Tools available to Tony:
- web_search: Brave search
- read_email: Gmail
- send_email: Gmail send
- read_case: RAG vector search
- remember: Store to memory
- recall: Fetch from memory
- http_get/post: Call any API
- write_code: Generate and validate Python
- push_code: Push to GitHub
- think: Log a thought to think_sessions
"""
import os
import json
import httpx
import asyncio
import psycopg2
from datetime import datetime
from typing import List, Dict, Any, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")

def log_agent_step(task_id: str, step: str, result: str, ok: bool):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id SERIAL PRIMARY KEY,
                task_id TEXT,
                step TEXT,
                result TEXT,
                ok BOOLEAN,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute(
            "INSERT INTO agent_runs (task_id, step, result, ok) VALUES (%s, %s, %s, %s)",
            (task_id, step, result[:2000], ok)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[AGENT] Log failed: {e}")

# --- TOOLS ---

async def tool_web_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                params={"q": query, "count": 5}
            )
            results = r.json().get("web", {}).get("results", [])
            return "\n".join(f"- {x['title']}: {x['description']}" for x in results[:5])
    except Exception as e:
        return f"Search failed: {e}"

async def tool_read_emails(query: str, max_results: int = 5) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{BACKEND_URL}/api/v1/gmail/search",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"},
                params={"query": query, "max_per_account": max_results}
            )
            emails = r.json().get("results", [])
            if not emails:
                return "No emails found."
            lines = []
            for e in emails[:5]:
                lines.append(f"From: {e.get('from','')} | {e.get('date','')[:16]}")
                lines.append(f"Subject: {e.get('subject','')}")
                lines.append(f"Snippet: {e.get('snippet','')[:150]}")
                lines.append("---")
            return "\n".join(lines)
    except Exception as e:
        return f"Email read failed: {e}"

async def tool_search_case(case_name: str, question: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Get cases
            r = await client.get(
                f"{BACKEND_URL}/api/v1/cases",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"}
            )
            cases = r.json().get("cases", [])
            target = next((c for c in cases if case_name.lower() in c["name"].lower() and c["status"] == "ready"), None)
            if not target:
                return f"No ready case found for '{case_name}'"
            r2 = await client.post(
                f"{BACKEND_URL}/api/v1/cases/query",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"},
                params={"case_id": target["id"], "question": question, "top_k": 5}
            )
            results = r2.json().get("results", [])
            if not results:
                return "No relevant case data found."
            lines = []
            for r in results:
                lines.append(f"[{r.get('date','')[:16]}] {r.get('sender','')}")
                lines.append(r.get("content", "")[:300])
                lines.append("---")
            return "\n".join(lines)
    except Exception as e:
        return f"Case search failed: {e}"

async def tool_remember(category: str, text: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{BACKEND_URL}/api/v1/memories",
                headers={"Authorization": f"Bearer {DEV_TOKEN}"},
                json={"category": category, "text": text}
            )
            return "Remembered." if r.status_code == 200 else f"Memory failed: {r.status_code}"
    except Exception as e:
        return f"Remember failed: {e}"

async def tool_http_get(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            return r.text[:2000]
    except Exception as e:
        return f"HTTP GET failed: {e}"

async def tool_think(thought: str) -> str:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO think_sessions (stage, content, created_at) VALUES (%s, %s, NOW())",
                    ("agent_thought", thought[:1000]))
        conn.commit()
        cur.close()
        conn.close()
        return "Thought logged."
    except Exception as e:
        return f"Think failed: {e}"

async def tool_watch_video(url: str, question: str = None) -> str:
    """Tony watches a YouTube video."""
    try:
        from app.core.vision import tony_study_video
        result = await tony_study_video(url, question)
        if "error" in result:
            return f"Could not watch video: {result['error']}"
        title = result.get("metadata", {}).get("title", "Unknown")
        return f"Watched: {title}\n\n{result.get('answer', 'No content extracted')}"
    except Exception as e:
        return f"Video watch failed: {e}"

async def tool_research_youtube(topic: str, max_videos: int = 3) -> str:
    """Tony searches YouTube and studies multiple videos on a topic."""
    try:
        from app.core.vision import tony_search_and_study_youtube
        result = await tony_search_and_study_youtube(topic, max_videos)
        if "error" in result:
            return f"YouTube research failed: {result['error']}"
        return f"Studied {result.get('videos_studied', 0)} videos on '{topic}':\n\n{result.get('synthesis', 'No synthesis available')}"
    except Exception as e:
        return f"YouTube research failed: {e}"

TOOLS = {
    "web_search": tool_web_search,
    "read_emails": tool_read_emails,
    "search_case": tool_search_case,
    "remember": tool_remember,
    "http_get": tool_http_get,
    "think": tool_think,
    "watch_video": tool_watch_video,
    "research_youtube": tool_research_youtube,
}

TOOL_DESCRIPTIONS = """
Available tools (call as JSON in your response):
- web_search(query) — search the web
- read_emails(query, max_results=5) — search Matthew's emails
- search_case(case_name, question) — search a legal case by name
- remember(category, text) — store something to memory
- http_get(url) — fetch a URL
- think(thought) — log a thought or reasoning step
- watch_video(url, question=None) — watch a YouTube video and understand it
- research_youtube(topic, max_videos=3) — search YouTube, watch top videos, synthesise

To use a tool, respond with:
TOOL: {"name": "tool_name", "args": {"arg1": "value1"}}

When done, respond with:
FINAL: your final answer to Matthew
"""

async def run_agent_task(task: str, max_steps: int = 10) -> Dict[str, Any]:
    """
    Run an agentic task loop.
    Tony reasons, uses tools, iterates, and produces a final answer.
    """
    import uuid
    task_id = str(uuid.uuid4())[:8]
    
    messages = [
        {
            "role": "user",
            "content": f"""You are Tony, Matthew's autonomous AI agent. 
            
Complete this task: {task}

{TOOL_DESCRIPTIONS}

Think step by step. Use tools as needed. When you have a complete answer, respond with FINAL: followed by your answer."""
        }
    ]
    
    steps = []
    final_answer = None
    
    for step_num in range(max_steps):
        # Call Gemini
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": messages,
                        "generationConfig": {"maxOutputTokens": 2048}
                    }
                )
                r.raise_for_status()
                response_text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            log_agent_step(task_id, f"step_{step_num}", f"LLM error: {e}", False)
            break
        
        messages.append({"role": "model", "content": response_text})
        steps.append({"step": step_num, "response": response_text[:500]})
        log_agent_step(task_id, f"step_{step_num}", response_text[:500], True)
        
        # Check for FINAL answer
        if "FINAL:" in response_text:
            final_answer = response_text.split("FINAL:", 1)[1].strip()
            break
        
        # Check for tool call
        if "TOOL:" in response_text:
            try:
                tool_json = response_text.split("TOOL:", 1)[1].strip()
                # Extract JSON
                start = tool_json.find("{")
                end = tool_json.rfind("}") + 1
                tool_call = json.loads(tool_json[start:end])
                tool_name = tool_call["name"]
                tool_args = tool_call.get("args", {})
                
                if tool_name in TOOLS:
                    tool_result = await TOOLS[tool_name](**tool_args)
                    log_agent_step(task_id, f"tool_{tool_name}", tool_result[:500], True)
                    messages.append({
                        "role": "user",
                        "content": f"Tool result for {tool_name}:\n{tool_result}\n\nContinue with the task."
                    })
                else:
                    messages.append({
                        "role": "user", 
                        "content": f"Tool '{tool_name}' not available. Available tools: {', '.join(TOOLS.keys())}"
                    })
            except Exception as e:
                messages.append({
                    "role": "user",
                    "content": f"Tool call failed: {e}. Try again with valid JSON."
                })
    
    return {
        "task_id": task_id,
        "task": task,
        "steps": len(steps),
        "final_answer": final_answer or "Agent did not produce a final answer.",
        "step_log": steps
    }
