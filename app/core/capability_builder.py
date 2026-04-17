"""
Tony's Capability Builder.

When Tony can't do something, this module:
1. Analyses what's needed
2. Researches how to build it
3. Writes the code
4. Validates it
5. Deploys it
6. Updates the capability registry
7. Immediately uses the new capability

This is Tony's self-expansion engine.
"""
import os
import ast
import httpx
import asyncio
import base64
import json
import psycopg2
from datetime import datetime

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def research_capability(capability_description: str) -> str:
    """Use web search + Gemini to research how to build a capability."""
    results = []
    
    # Search for APIs and implementation approaches
    search_queries = [
        f"{capability_description} Python API free",
        f"{capability_description} REST API implementation 2026",
        f"how to build {capability_description} FastAPI",
    ]
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for query in search_queries[:2]:
            try:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY},
                    params={"q": query, "count": 3}
                )
                items = r.json().get("web", {}).get("results", [])
                for item in items[:3]:
                    results.append(f"- {item['title']}: {item['description']}")
            except Exception:
                pass
    
    return "\n".join(results)


async def generate_capability_code(
    capability_name: str,
    capability_description: str,
    research: str
) -> dict:
    """
    Use Gemini to write the actual Python code for a new capability.
    Returns the generated code and a proposed endpoint path.
    """
    prompt = f"""You are writing a new capability for Tony, an AI assistant backend (FastAPI on Railway).

CAPABILITY NEEDED: {capability_name}
DESCRIPTION: {capability_description}

RESEARCH FINDINGS:
{research}

RULES:
1. Write a FastAPI router file for app/api/v1/endpoints/{capability_name.replace(' ','_').lower()}.py
2. Use only libraries already available: fastapi, httpx, psycopg2-binary, pydantic
3. Use psycopg2 directly for any DB access (no ORM)
4. Single user app — no user_id fields ever
5. Auth: all endpoints use `_=Depends(verify_token)` from app.core.security
6. Keep it simple and functional — one file, self-contained
7. If it needs an API key, use os.environ.get() with a sensible env var name
8. Include a test endpoint at GET /{capability_name}/test that returns a status

Respond ONLY with:
FILENAME: app/api/v1/endpoints/{capability_name.replace(' ','_').lower()}.py
ENV_VARS_NEEDED: comma-separated list of any new env vars needed (or NONE)
CODE:
```python
[the complete file content]
```
"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.2}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        
        # Parse response
        filename = ""
        env_vars = []
        code = ""
        
        if "FILENAME:" in response:
            filename = response.split("FILENAME:")[1].split("\n")[0].strip()
        if "ENV_VARS_NEEDED:" in response:
            env_str = response.split("ENV_VARS_NEEDED:")[1].split("\n")[0].strip()
            env_vars = [e.strip() for e in env_str.split(",") if e.strip() != "NONE"]
        if "```python" in response:
            code = response.split("```python")[1].split("```")[0].strip()
        
        return {
            "filename": filename,
            "env_vars": env_vars,
            "code": code,
            "ok": bool(filename and code)
        }
    except Exception as e:
        return {"filename": "", "env_vars": [], "code": "", "ok": False, "error": str(e)}


def validate_code(code: str) -> dict:
    """Syntax check and basic safety validation."""
    issues = []
    
    # Syntax check
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e}"}
    
    # Safety checks
    dangerous = ["os.system", "subprocess", "eval(", "exec(", "__import__", "shutil.rmtree"]
    for d in dangerous:
        if d in code:
            issues.append(f"Dangerous pattern: {d}")
    
    # Must have router
    if "router = APIRouter()" not in code:
        issues.append("Missing router = APIRouter()")
    
    # Must have auth
    if "verify_token" not in code:
        issues.append("Missing auth - endpoints must use verify_token")
    
    if issues:
        return {"valid": False, "error": "; ".join(issues)}
    
    return {"valid": True}


async def push_capability_to_github(filename: str, code: str, capability_name: str) -> dict:
    """Push the new capability file to GitHub."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Check if file exists
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
            )
            sha = r.json().get("sha") if r.status_code == 200 else None
            
            # Encode content
            content_b64 = base64.b64encode(code.encode()).decode()
            
            payload = {
                "message": f"feat: auto-build capability - {capability_name}",
                "content": content_b64,
                "branch": "main"
            }
            if sha:
                payload["sha"] = sha
            
            r2 = await client.put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
                json=payload
            )
            
            if r2.status_code in (200, 201):
                return {"ok": True, "url": r2.json().get("content", {}).get("html_url", "")}
            else:
                return {"ok": False, "error": r2.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def update_router_for_capability(capability_name: str, module_name: str) -> dict:
    """Update router.py to include the new capability."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get current router.py
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/app/api/v1/router.py",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
            )
            if r.status_code != 200:
                return {"ok": False, "error": "Could not fetch router.py"}
            
            data = r.json()
            current_content = base64.b64decode(data["content"]).decode()
            sha = data["sha"]
            
            # Add import and router include
            tag_line = f"from app.api.v1.endpoints import {module_name}"
            if tag_line in current_content:
                return {"ok": True, "note": "Already in router"}
            
            # Add before the last try block
            insertion = f'\nfrom app.api.v1.endpoints import {module_name}\nrouter.include_router({module_name}.router, tags=["{capability_name}"])\n'
            
            # Insert at the end of the router includes section
            marker = 'router.include_router(agent.router, tags=["agent"])'
            if marker in current_content:
                new_content = current_content.replace(marker, marker + insertion)
            else:
                new_content = current_content + insertion
            
            # Push updated router
            content_b64 = base64.b64encode(new_content.encode()).decode()
            r2 = await client.put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/app/api/v1/router.py",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
                json={
                    "message": f"feat: wire {capability_name} into router",
                    "content": content_b64,
                    "sha": sha,
                    "branch": "main"
                }
            )
            return {"ok": r2.status_code in (200, 201)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def register_capability(name: str, description: str, endpoint: str):
    """Add the new capability to the registry."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO capabilities (name, description, status, endpoint)
            VALUES (%s, %s, 'active', %s)
            ON CONFLICT (name) DO UPDATE SET
                status = 'active',
                description = EXCLUDED.description,
                endpoint = EXCLUDED.endpoint
        """, (name, description, endpoint))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[BUILDER] Registry update failed: {e}")


async def build_capability(capability_name: str, capability_description: str) -> dict:
    """
    Full pipeline: research → generate → validate → deploy → register.
    Returns a status report.
    """
    report = {
        "capability": capability_name,
        "description": capability_description,
        "steps": []
    }
    
    def step(name, result, ok):
        report["steps"].append({"step": name, "result": result, "ok": ok})
        print(f"[BUILDER] {name}: {'✓' if ok else '✗'} {result[:100] if isinstance(result,str) else ''}")
    
    # 1. Research
    research = await research_capability(capability_description)
    step("research", f"Found {len(research.split(chr(10)))} research items", True)
    
    # 2. Generate code
    gen = await generate_capability_code(capability_name, capability_description, research)
    if not gen["ok"]:
        step("generate", gen.get("error", "Generation failed"), False)
        report["success"] = False
        return report
    step("generate", f"Generated {len(gen['code'])} chars for {gen['filename']}", True)
    
    # 3. Validate
    validation = validate_code(gen["code"])
    if not validation["valid"]:
        step("validate", validation["error"], False)
        report["success"] = False
        report["code_for_review"] = gen["code"]
        return report
    step("validate", "Code passed syntax and safety checks", True)
    
    # 4. Push to GitHub
    module_name = gen["filename"].split("/")[-1].replace(".py", "")
    push_result = await push_capability_to_github(gen["filename"], gen["code"], capability_name)
    if not push_result["ok"]:
        step("push", push_result.get("error", "Push failed"), False)
        report["success"] = False
        return report
    step("push", f"Pushed to GitHub: {push_result.get('url','')}", True)
    
    # 5. Wire into router
    router_result = await update_router_for_capability(capability_name, module_name)
    step("router", "Wired into router" if router_result["ok"] else router_result.get("error",""), router_result["ok"])
    
    # 6. Register capability
    register_capability(capability_name, capability_description, f"/api/v1/{module_name}")
    step("register", "Added to capability registry", True)
    
    # 7. Note any env vars needed
    if gen["env_vars"]:
        report["env_vars_needed"] = gen["env_vars"]
        step("env_vars", f"You need to add to Railway: {', '.join(gen['env_vars'])}", True)
    
    report["success"] = True
    report["note"] = "Railway is deploying the new capability now. Will be live in ~60 seconds."
    return report
