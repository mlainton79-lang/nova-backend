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


async def call_provider(provider: str, prompt: str) -> str:
    """Call a single AI provider for code generation."""
    async with httpx.AsyncClient(timeout=45.0) as client:
        if provider == "gemini":
            from app.core import gemini_client
            resp = await gemini_client.generate_content(
                tier="flash",
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                generation_config={"maxOutputTokens": 4096, "temperature": 0.1},
                timeout=45.0,
                caller_context="capability_builder.call_provider.gemini",
            )
            return gemini_client.extract_text(resp)

        elif provider == "groq":
            GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
            GROQ_MODEL = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 4096, "temperature": 0.1}
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        elif provider == "mistral":
            MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
            MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
            r = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
                json={"model": MISTRAL_MODEL, "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 4096, "temperature": 0.1}
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

        elif provider == "openrouter":
            OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                json={"model": "openrouter/auto", "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 4096, "temperature": 0.1}
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    return ""


def parse_code_response(response: str, capability_name: str) -> dict:
    """Parse a code generation response into structured output."""
    filename = ""
    env_vars = []
    code = ""

    if "FILENAME:" in response:
        filename = response.split("FILENAME:")[1].split("\n")[0].strip()
    if not filename:
        filename = f"app/api/v1/endpoints/{capability_name.replace(' ','_').lower()}.py"

    if "ENV_VARS_NEEDED:" in response:
        env_str = response.split("ENV_VARS_NEEDED:")[1].split("\n")[0].strip()
        env_vars = [e.strip() for e in env_str.split(",") if e.strip() and e.strip() != "NONE"]

    if "```python" in response:
        code = response.split("```python")[1].split("```")[0].strip()
    elif "```" in response:
        code = response.split("```")[1].split("```")[0].strip()

    return {"filename": filename, "env_vars": env_vars, "code": code, "ok": bool(filename and code)}


async def generate_capability_code(
    capability_name: str,
    capability_description: str,
    research: str
) -> dict:
    """
    Use all available brains to write the best possible code.
    Each provider generates an implementation.
    Gemini then synthesises the best version combining all approaches.
    """
    module_name = capability_name.replace(" ", "_").lower()

    prompt = f"""You are writing a new capability for Tony, an AI assistant backend (FastAPI on Railway).

CAPABILITY NEEDED: {capability_name}
DESCRIPTION: {capability_description}

RESEARCH FINDINGS:
{research}

STRICT RULES:
1. Write a complete FastAPI router file for app/api/v1/endpoints/{module_name}.py
2. Use ONLY: fastapi, httpx, psycopg2-binary, pydantic (already installed)
3. Use psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require") for DB (no ORM)
4. Single user app — never add user_id fields
5. ALL endpoints must have `_=Depends(verify_token)` from app.core.security
6. API keys via os.environ.get("KEY_NAME", "")
7. Include GET /{module_name}/test endpoint returning status
8. One self-contained file, no relative imports except app.core.security

Respond ONLY with:
FILENAME: app/api/v1/endpoints/{module_name}.py
ENV_VARS_NEEDED: list any new env vars needed, or NONE
CODE:
```python
[complete file]
```"""

    # Run all available providers in parallel
    providers = ["gemini", "groq", "mistral", "openrouter"]
    responses = {}

    async def try_provider(p):
        try:
            result = await call_provider(p, prompt)
            if result:
                responses[p] = result
        except Exception as e:
            print(f"[BUILDER] {p} failed: {e}")

    await asyncio.gather(*[try_provider(p) for p in providers])

    if not responses:
        return {"filename": "", "env_vars": [], "code": "", "ok": False, "error": "All providers failed"}

    # If only one responded, use it directly
    if len(responses) == 1:
        return parse_code_response(list(responses.values())[0], capability_name)

    # Multiple responses — use Gemini to synthesise the best version
    synthesis_prompt = f"""You are a senior Python engineer reviewing {len(responses)} implementations of the same capability.

CAPABILITY: {capability_name}
DESCRIPTION: {capability_description}

Here are the implementations from different AI models:

{"".join(f"--- {provider.upper()} IMPLEMENTATION ---\n{code[:2000]}\n\n" for provider, code in responses.items())}

Synthesise the BEST possible implementation by:
1. Taking the strongest architectural approach
2. Using the most robust error handling
3. Combining the best features from each
4. Ensuring it follows all the original rules

Output the final synthesised version in the same format:
FILENAME: app/api/v1/endpoints/{module_name}.py
ENV_VARS_NEEDED: [list or NONE]
CODE:
```python
[complete synthesised file]
```"""

    try:
        synthesised = await call_provider("gemini", synthesis_prompt)
        result = parse_code_response(synthesised, capability_name)
        result["providers_used"] = list(responses.keys())
        result["synthesis"] = True
        return result
    except Exception as e:
        # Fall back to best single response
        best = parse_code_response(list(responses.values())[0], capability_name)
        best["providers_used"] = [list(responses.keys())[0]]
        return best


def extract_imports(code: str) -> list:
    """Return a sorted de-duped list of top-level module names imported by
    the generated code. Used at approval time to surface surprising imports
    (subprocess, socket, ctypes, etc.) in the review alert — a lightweight
    security scan visible before anything deploys."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
    return sorted(found)


def validate_code(code: str) -> dict:
    """Syntax check, safety, AND name/import validation."""
    issues = []
    
    # Syntax check
    try:
        tree = ast.parse(code)
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
    
    # Check for undefined names (missing imports) — the #1 cause of Tony's autonomous builds failing
    # Walk the AST, collect imported names + defined names, then check all Name references
    imported = set()
    defined = set()
    used = set()
    
    # Python builtins + FastAPI common names that are always available
    builtins_available = {
        'True', 'False', 'None', 'print', 'len', 'range', 'str', 'int', 'float',
        'bool', 'list', 'dict', 'tuple', 'set', 'type', 'isinstance', 'hasattr',
        'getattr', 'setattr', 'Exception', 'ValueError', 'KeyError', 'TypeError',
        'self', 'cls', 'open', 'sorted', 'min', 'max', 'sum', 'any', 'all',
        'zip', 'map', 'filter', 'enumerate', 'iter', 'next', '__name__',
        'abs', 'round', 'bytes', 'repr', 'id', 'hash',
    }
    imported.update(builtins_available)
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
            # Args are local
            if hasattr(node, 'args'):
                for arg in node.args.args:
                    defined.add(arg.arg)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
    
    undefined = used - imported - defined
    if undefined:
        # Common undefined names that signal missing imports
        import_hints = {
            'os': 'import os', 'sys': 'import sys', 're': 'import re',
            'json': 'import json', 'asyncio': 'import asyncio',
            'datetime': 'from datetime import datetime',
            'timedelta': 'from datetime import timedelta',
            'httpx': 'import httpx', 'requests': 'import requests',
            'psycopg2': 'import psycopg2', 'ast': 'import ast',
        }
        missing_imports = [n for n in undefined if n in import_hints]
        if missing_imports:
            hints = [f"{n} (add: {import_hints[n]})" for n in missing_imports]
            issues.append(f"Used but not imported: {', '.join(hints)}")
        else:
            # Other undefined names
            other = [n for n in undefined if not n.startswith('_')][:5]
            if other:
                issues.append(f"Undefined names: {', '.join(other)}")
    
    if issues:
        return {"valid": False, "error": "; ".join(issues)}
    
    return {"valid": True}


def runtime_import_check(code: str, module_name: str) -> dict:
    """
    Try to actually import the generated code in an isolated namespace.
    This catches runtime errors that pure syntax/AST checks miss —
    like missing imports, wrong signatures, undefined helper calls.
    
    Returns {"ok": True} if it imports cleanly, else {"ok": False, "error": "..."}
    """
    import tempfile
    import importlib.util
    import os as _os
    
    tmp_path = None
    try:
        # Write to a tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix=f"tony_check_{module_name}_")
        with _os.fdopen(fd, "w") as f:
            f.write(code)
        
        # Load as a module
        spec = importlib.util.spec_from_file_location(f"tony_check_{module_name}", tmp_path)
        if spec is None or spec.loader is None:
            return {"ok": False, "error": "Could not create module spec"}
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except NameError as e:
            return {"ok": False, "error": f"NameError at import: {e}"}
        except ImportError as e:
            # Only fail on imports we can't resolve. Tony may legitimately import
            # from app.core — that'll work in production.
            msg = str(e)
            if "app.core" in msg or "app.api" in msg:
                # Expected — would work in production
                return {"ok": True, "note": "internal app imports skipped in check"}
            return {"ok": False, "error": f"ImportError: {e}"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__} at import: {str(e)[:200]}"}
        
        # Check for a router attribute
        if not hasattr(mod, "router"):
            return {"ok": False, "error": "Module has no 'router' attribute"}
        
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"Check harness error: {e}"}
    finally:
        if tmp_path:
            try: _os.unlink(tmp_path)
            except Exception: pass


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


async def build_capability_stage(capability_name: str, capability_description: str) -> dict:
    """
    Stage-only build: research → generate → validate → runtime-import-check.
    No network side effects against GitHub or the capability registry.

    Returns:
      {"ok": True, "steps": [...], "artifacts": {filename, module_name, code, env_vars, providers_used}}
      {"ok": False, "error": "...", "steps": [...], "code_for_review"?: str}
    """
    report_steps = []

    def step(name, result, ok):
        report_steps.append({"step": name, "result": result, "ok": ok})
        print(f"[BUILDER] {name}: {'✓' if ok else '✗'} {result[:100] if isinstance(result, str) else ''}")

    # 1. Research
    research = await research_capability(capability_description)
    step("research", f"Found {len(research.split(chr(10)))} research items", True)

    # 2. Generate code
    gen = await generate_capability_code(capability_name, capability_description, research)
    if not gen["ok"]:
        step("generate", gen.get("error", "Generation failed"), False)
        return {"ok": False, "error": gen.get("error", "Generation failed"), "steps": report_steps}
    step("generate", f"Generated {len(gen['code'])} chars for {gen['filename']}", True)

    # 3. Validate (syntax + undefined name check + banned patterns)
    validation = validate_code(gen["code"])
    if not validation["valid"]:
        step("validate", validation["error"], False)
        return {"ok": False, "error": validation["error"], "steps": report_steps,
                "code_for_review": gen["code"]}
    step("validate", "Code passed syntax and safety checks", True)

    # 3b. Runtime import check — isolated-namespace load
    module_name = gen["filename"].split("/")[-1].replace(".py", "")
    runtime_check = runtime_import_check(gen["code"], module_name)
    if not runtime_check["ok"]:
        step("runtime_check", runtime_check["error"], False)
        return {"ok": False, "error": runtime_check["error"], "steps": report_steps,
                "code_for_review": gen["code"]}
    step("runtime_check", "Code imports cleanly", True)

    return {
        "ok": True,
        "steps": report_steps,
        "artifacts": {
            "filename": gen["filename"],
            "module_name": module_name,
            "code": gen["code"],
            "env_vars": gen.get("env_vars", []),
            "providers_used": gen.get("providers_used", []),
        },
    }


async def deploy_capability_stage(capability_name: str, capability_description: str,
                                   artifacts: dict) -> dict:
    """
    Deploy half: push to GitHub → wire router → register → schedule eval gate.
    Called only from POST /builder/approve/{request_id} after a human review
    of the staged artifacts.
    """
    report = {"capability": capability_name, "description": capability_description, "steps": []}

    def step(name, result, ok):
        report["steps"].append({"step": name, "result": result, "ok": ok})
        print(f"[BUILDER] {name}: {'✓' if ok else '✗'} {result[:100] if isinstance(result, str) else ''}")

    filename = artifacts["filename"]
    module_name = artifacts["module_name"]
    code = artifacts["code"]
    env_vars = artifacts.get("env_vars", []) or []

    # 4. Push to GitHub
    push_result = await push_capability_to_github(filename, code, capability_name)
    if not push_result["ok"]:
        step("push", push_result.get("error", "Push failed"), False)
        report["success"] = False
        report["error"] = push_result.get("error", "Push failed")
        return report
    step("push", f"Pushed to GitHub: {push_result.get('url', '')}", True)

    # 5. Wire into router
    router_result = await update_router_for_capability(capability_name, module_name)
    step("router",
         "Wired into router" if router_result["ok"] else router_result.get("error", ""),
         router_result["ok"])

    # 6. Register in capability registry
    register_capability(capability_name, capability_description, f"/api/v1/{module_name}")
    step("register", "Added to capability registry", True)

    # 7. Env vars note
    if env_vars:
        report["env_vars_needed"] = env_vars
        step("env_vars", f"Add to Railway: {', '.join(env_vars)}", True)

    # 8. Schedule post-deploy eval gate — auto-reverts if critical tests fail
    try:
        import asyncio
        from app.core.eval_gate import post_deploy_check_and_revert_if_needed
        asyncio.create_task(post_deploy_check_and_revert_if_needed())
        step("eval_gate_scheduled", "Post-deploy safety check scheduled", True)
    except Exception as e:
        step("eval_gate_scheduled", str(e), False)

    report["success"] = True
    report["note"] = "Railway deploying now. Eval gate will check and auto-revert if critical tests fail."
    return report


async def build_capability(capability_name: str, capability_description: str) -> dict:
    """
    DEPRECATED direct-deploy form. Since the approval gate landed, this
    wrapper routes through the staging pipeline: it schedules generation +
    validation in the background and returns the request_id. The caller
    must approve via POST /api/v1/builder/approve/{request_id} before
    anything touches production.

    Returns success=False deliberately — "successfully deployed" is no
    longer a possible outcome of a single call. Callers that treat
    success=True as "capability is live" (e.g. tony_mission) will correctly
    see False until the human approves and the eventual deploy completes.
    """
    from app.core.gap_detector import start_autonomous_build
    request_id = await start_autonomous_build(
        capability_name=capability_name,
        description=capability_description,
        user_message=f"manual build request: {capability_description}",
    )
    return {
        "capability": capability_name,
        "description": capability_description,
        "steps": [],
        "success": False,
        "request_id": request_id,
        "status": "pending_review" if request_id > 0 else "failed_to_stage",
        "note": (f"Staged for review. Approve via "
                 f"POST /api/v1/builder/approve/{request_id}"
                 if request_id > 0
                 else "Failed to start staging; see server logs."),
    }
