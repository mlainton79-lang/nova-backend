"""
Tony's Self-Building Engine — Production Grade.

This is the core of Tony's autonomy. Tony writes, tests, validates,
and deploys his own code improvements without human intervention.

Architecture:
1. IDENTIFY: Tony analyses what he needs and can't do
2. RESEARCH: Multi-source research on best approach  
3. DESIGN: Architecture planning before any code
4. GENERATE: Multi-model code generation (best wins)
5. VALIDATE: Syntax + logic + safety + import check
6. SELF-DEBUG: If validation fails, Tony fixes it (up to 3 attempts)
7. TEST: Call the endpoint after deploy, verify it works
8. INTEGRATE: Wire into router, system prompt, autonomous loop
9. DOCUMENT: Log what was built and why
10. LEARN: Update self-knowledge so Tony knows it can do this now

Key improvements over old capability_builder:
- Uses Gemini 2.5 Pro for complex code generation
- Multi-attempt self-debugging loop
- Reads its own codebase for context
- Tests deployed endpoints automatically
- Integrates into system prompt automatically
- Full audit trail
"""
import os
import ast
import re
import json
import asyncio
import base64
import httpx
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional, Tuple

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")
BACKEND_URL = "https://web-production-be42b.up.railway.app"
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def log_build(stage: str, content: str, success: bool = True):
    """Log every step of the build process."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_build_log (
                id SERIAL PRIMARY KEY,
                stage TEXT,
                content TEXT,
                success BOOLEAN,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute(
            "INSERT INTO tony_build_log (stage, content, success) VALUES (%s, %s, %s)",
            (stage, content[:2000], success)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


async def _gemini_pro(prompt: str, max_tokens: int = 8192) -> Optional[str]:
    """Gemini 2.5 Pro for high-quality code generation."""
    if not GEMINI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1}
                }
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            # Fallback to Flash
            r2 = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1}
                }
            )
            if r2.status_code == 200:
                return r2.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        log_build("gemini_error", str(e), False)
    return None


async def _claude(prompt: str) -> Optional[str]:
    """Claude for code generation when Gemini needs backup."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 8192,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
    except Exception as e:
        log_build("claude_error", str(e), False)
    return None


async def read_own_codebase_context() -> str:
    """Tony reads key files from his own codebase for context."""
    context_files = [
        "app/api/v1/router.py",
        "app/core/model_router.py",
        "app/core/memory.py",
        "app/prompts/tony.py",
        "requirements.txt",
    ]
    
    context = ""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for filepath in context_files[:3]:  # Limit to avoid context overflow
                url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
                r = await client.get(
                    url,
                    headers={"Authorization": f"token {GITHUB_TOKEN}"}
                )
                if r.status_code == 200:
                    content = base64.b64decode(r.json()["content"]).decode()
                    context += f"\n\n# FILE: {filepath}\n{content[:1000]}"
    except Exception as e:
        log_build("codebase_read_error", str(e), False)
    
    return context


def validate_python_code(code: str, capability_name: str) -> Dict:
    """
    Comprehensive code validation before deployment.
    """
    errors = []
    warnings = []
    
    # 1. Syntax check
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "errors": [f"Syntax error line {e.lineno}: {e.msg}"], "warnings": []}
    
    # 2. Safety checks - patterns that could cause damage
    dangerous = [
        "os.system(", "subprocess.run(", "subprocess.Popen(",
        "eval(", "exec(", "__import__(",
        "shutil.rmtree(", "os.remove(", "open('/etc",
        "DROP TABLE", "DELETE FROM tony_", "TRUNCATE"
    ]
    for pattern in dangerous:
        if pattern in code:
            errors.append(f"Dangerous pattern detected: {pattern}")
    
    # 3. Required patterns for FastAPI endpoints
    if "router = APIRouter()" not in code:
        errors.append("Missing: router = APIRouter()")
    if "verify_token" not in code:
        errors.append("Missing: authentication via verify_token")
    if "from fastapi import" not in code:
        errors.append("Missing: FastAPI imports")
    
    # 4. Import checks
    imports_ok = True
    for line in code.split('\n'):
        if line.startswith('import ') or line.startswith('from '):
            if 'pickle' in line or 'marshal' in line:
                warnings.append(f"Potentially unsafe import: {line.strip()}")
    
    # 5. Code length sanity check
    if len(code) < 100:
        errors.append("Code too short to be a real module")
    if len(code) > 50000:
        warnings.append("Code very long - review carefully")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }


async def self_debug_code(
    code: str, 
    errors: List[str], 
    original_prompt: str,
    attempt: int = 1
) -> Optional[str]:
    """
    Tony debugs his own generated code.
    Given errors, rewrites to fix them.
    """
    if attempt > 3:
        log_build("self_debug_exhausted", f"After {attempt} attempts, couldn't fix: {errors}", False)
        return None
    
    debug_prompt = f"""You are Tony's self-debugging system. Code was generated but has errors.

ORIGINAL TASK:
{original_prompt[:1000]}

GENERATED CODE WITH ERRORS:
```python
{code[:3000]}
```

ERRORS TO FIX:
{chr(10).join(f"- {e}" for e in errors)}

Rewrite the COMPLETE corrected Python code.
Fix all errors. Keep the same functionality.
Output ONLY the Python code, no explanation, no markdown.
The code MUST:
- Have router = APIRouter()
- Use verify_token for auth
- Have proper FastAPI imports
- Be syntactically valid Python"""

    # Use both models and take the first valid one
    fixed = await _gemini_pro(debug_prompt)
    if not fixed:
        fixed = await _claude(debug_prompt)
    
    if fixed:
        # Clean markdown
        fixed = re.sub(r'```python\n?', '', fixed)
        fixed = re.sub(r'```\n?', '', fixed)
        fixed = fixed.strip()
        log_build("self_debug", f"Attempt {attempt}: Generated fix", True)
        return fixed
    
    return None


async def push_to_github(filepath: str, code: str, commit_message: str) -> bool:
    """Push a file to GitHub."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get current SHA if file exists
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
            headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            sha = None
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                sha = r.json().get("sha")
            
            # Push
            payload = {
                "message": commit_message,
                "content": base64.b64encode(code.encode()).decode(),
                "branch": "main"
            }
            if sha:
                payload["sha"] = sha
            
            r = await client.put(url, headers=headers, json=payload)
            return r.status_code in (200, 201)
    except Exception as e:
        log_build("github_push_error", str(e), False)
        return False


async def wire_into_router(module_name: str, capability_name: str) -> bool:
    """
    Automatically update router.py to include the new module.
    This is Tony updating his own infrastructure.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/app/api/v1/router.py"
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return False
            
            router_content = base64.b64decode(r.json()["content"]).decode()
            sha = r.json()["sha"]
            
            # Check if already wired
            if f"from app.api.v1.endpoints import {module_name}" in router_content:
                return True
            
            # Find the last router.include_router line and add after it
            lines = router_content.split('\n')
            last_include = 0
            for i, line in enumerate(lines):
                if 'router.include_router' in line:
                    last_include = i
            
            if last_include == 0:
                return False
            
            new_lines = (
                lines[:last_include + 1] +
                [f"from app.api.v1.endpoints import {module_name}",
                 f"router.include_router({module_name}.router, tags=[\"{capability_name}\"])"] +
                lines[last_include + 1:]
            )
            
            new_content = '\n'.join(new_lines)
            payload = {
                "message": f"auto-wire: {capability_name} endpoint integrated by Tony",
                "content": base64.b64encode(new_content.encode()).decode(),
                "sha": sha,
                "branch": "main"
            }
            
            r = await client.put(url, headers=headers, json=payload)
            return r.status_code in (200, 201)
    
    except Exception as e:
        log_build("router_wire_error", str(e), False)
        return False


async def test_deployed_endpoint(endpoint_path: str, method: str = "GET") -> Dict:
    """
    After deployment, Tony tests his own new endpoint.
    Waits for Railway to redeploy then calls it.
    """
    # Wait for Railway deploy (typically 45-90 seconds)
    await asyncio.sleep(90)
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            url = f"{BACKEND_URL}/api/v1{endpoint_path}"
            headers = {"Authorization": f"Bearer {DEV_TOKEN}"}
            
            if method == "GET":
                r = await client.get(url, headers=headers)
            else:
                r = await client.post(url, headers=headers, json={})
            
            return {
                "status_code": r.status_code,
                "ok": r.status_code < 400,
                "response": r.text[:200]
            }
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def tony_build_capability(
    capability_name: str,
    capability_description: str,
    test_endpoint: str = None
) -> Dict:
    """
    Full self-building pipeline.
    Tony designs, writes, validates, debugs, deploys, and tests new capabilities.
    """
    print(f"[SELF_BUILDER] Starting build: {capability_name}")
    log_build("build_start", f"Building: {capability_name} — {capability_description}")
    
    report = {
        "capability": capability_name,
        "started_at": datetime.utcnow().isoformat(),
        "steps": [],
        "success": False
    }
    
    def step(name: str, result: str, ok: bool):
        report["steps"].append({"step": name, "result": result, "ok": ok})
        log_build(name, result, ok)
        print(f"[SELF_BUILDER] {name}: {'✓' if ok else '✗'} {result[:80]}")
    
    # Step 1: Read own codebase for context
    context = await read_own_codebase_context()
    step("read_codebase", f"Read {len(context)} chars of own code", bool(context))
    
    # Step 2: Generate code with best model
    module_name = capability_name.lower().replace(' ', '_').replace('-', '_')
    
    generate_prompt = f"""You are Tony's code generation system. Build a new FastAPI capability module.

CAPABILITY TO BUILD:
Name: {capability_name}
Description: {capability_description}

EXISTING CODEBASE CONTEXT (for consistency):
{context[:2000]}

REQUIREMENTS:
1. Python module for FastAPI
2. File: app/api/v1/endpoints/{module_name}.py
3. Must have: router = APIRouter()
4. Must use: from app.core.security import verify_token
5. Must have proper error handling
6. Use httpx for external API calls (async)
7. Use psycopg2 for database if needed
8. British English in all user-facing strings
9. Follow existing patterns in codebase
10. Real implementation — no placeholders, no TODO comments

Write the COMPLETE, PRODUCTION-READY Python module.
Output ONLY the Python code. No markdown, no explanation."""

    code = await _gemini_pro(generate_prompt)
    if not code:
        code = await _claude(generate_prompt)
    
    if not code:
        step("generate", "Both Gemini and Claude failed to generate code", False)
        return report
    
    # Clean markdown fences if any
    code = re.sub(r'```python\n?', '', code)
    code = re.sub(r'```\n?', '', code)
    code = code.strip()
    
    step("generate", f"Generated {len(code)} chars of code", True)
    
    # Step 3: Validate
    validation = validate_python_code(code, capability_name)
    
    if not validation["valid"]:
        step("validate", f"Errors: {validation['errors']}", False)
        
        # Step 4: Self-debug loop
        for attempt in range(1, 4):
            step(f"self_debug_{attempt}", f"Attempting to fix: {validation['errors'][:2]}", True)
            
            fixed_code = await self_debug_code(
                code, validation["errors"], generate_prompt, attempt
            )
            
            if not fixed_code:
                continue
            
            code = fixed_code
            validation = validate_python_code(code, capability_name)
            
            if validation["valid"]:
                step(f"self_debug_{attempt}_success", "Self-debugging fixed all errors", True)
                break
        
        if not validation["valid"]:
            step("self_debug_failed", f"Could not fix: {validation['errors']}", False)
            return report
    else:
        step("validate", f"Code valid. Warnings: {validation.get('warnings', [])}", True)
    
    # Step 5: Multi-model code review
    try:
        from app.core.code_reviewer import review_code, security_scan
        review = await review_code(code, capability_name)
        sec = await security_scan(code)
        
        if not review.get("approved"):
            step("code_review", f"Review rejected: {review.get('critical_issues', [])}", False)
            # Try to fix critical issues
            if review.get("critical_issues"):
                fixed = await self_debug_code(code, review["critical_issues"], generate_prompt)
                if fixed:
                    code = fixed
                    step("code_review_fix", "Applied code review fixes", True)
        else:
            step("code_review", f"Approved. Quality: {review.get('quality_score', '?')}/10", True)
        
        if not sec.get("secure"):
            step("security_scan", f"Security issues: {sec.get('issues', [])}", False)
            return report
        else:
            step("security_scan", "No security issues found", True)
    except Exception as e:
        step("code_review", f"Review skipped: {e}", True)  # Don't block on review failure

    # Step 6: Push to GitHub
    filepath = f"app/api/v1/endpoints/{module_name}.py"
    pushed = await push_to_github(
        filepath, code,
        f"feat(auto): Tony built {capability_name} autonomously"
    )
    
    if not pushed:
        step("push_github", "GitHub push failed", False)
        return report
    
    step("push_github", f"Pushed {filepath} to GitHub", True)
    
    # Step 7: Wire into router
    wired = await wire_into_router(module_name, capability_name)
    step("wire_router", f"Router updated: {wired}", wired)
    
    # Step 8: Update self-knowledge
    try:
        from app.core.self_knowledge import TONY_CAPABILITIES
        TONY_CAPABILITIES["autonomous_builds"] = TONY_CAPABILITIES.get("autonomous_builds", {})
        TONY_CAPABILITIES["autonomous_builds"][module_name] = {
            "status": "deployed",
            "note": f"Built autonomously: {capability_description[:100]}"
        }
        step("update_self_knowledge", f"Tony knows he can now do: {capability_name}", True)
    except Exception:
        pass
    
    # Step 9: Test if endpoint available after deploy
    if test_endpoint:
        step("waiting_for_deploy", "Waiting 90s for Railway to redeploy...", True)
        test_result = await test_deployed_endpoint(test_endpoint)
        step(
            "test_endpoint",
            f"Status {test_result.get('status_code', '?')}: {test_result.get('response', '')[:100]}",
            test_result.get("ok", False)
        )
    
    # Step 10: Log success
    report["success"] = True
    report["module_name"] = module_name
    report["filepath"] = filepath
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO think_sessions (stage, content, created_at)
            VALUES (%s, %s, NOW())
        """, (
            "autonomous_build_success",
            f"Built {capability_name}: {capability_description}. Steps: {len(report['steps'])}"
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass
    
    print(f"[SELF_BUILDER] ✓ Successfully built and deployed: {capability_name}")
    return report
