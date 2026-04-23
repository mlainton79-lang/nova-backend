"""
Multi-Agent Capability Builder.

Replaces the linear capability_builder with a role-separated workflow:
  1. ARCHITECT — takes the capability name, writes a spec (what it does, 
     inputs, outputs, key logic, error modes)
  2. CODER — takes the spec, writes the FastAPI router code
  3. CRITIC — reviews the code for: validation rules, security issues,
     error handling, Tony voice, Matthew-specific context awareness
  4. REVISOR — takes code + critique, fixes all raised issues
  5. FINAL VALIDATOR — runs validate_code + runtime_import_check
  
Each role is an independent Gemini call with a focused prompt. The multi-pass
review catches issues a single LLM would miss by committing to its own draft.

Feeds into the existing capability_builder.push_capability_to_github for 
the actual deploy. Same eval_gate safety net applies.
"""
import os
import httpx
import json
from typing import Dict, Optional


ARCHITECT_PROMPT = """You are the Architect for Tony's capability builder. Matthew asked for a new capability: '{capability_name}'.

Your ONLY job: produce a specification. Do NOT write code yet.

Return STRICT JSON:
{{
  "name": "slug_case_name",
  "description": "one-line summary",
  "inputs": ["what the endpoint accepts"],
  "outputs": ["what it returns"],
  "logic_steps": ["ordered steps the implementation should follow"],
  "error_modes": ["things that could fail + how to handle"],
  "dependencies": ["libraries or other tony modules needed"],
  "endpoint_path": "/api/v1/something",
  "http_method": "GET|POST",
  "auth_required": true
}}

Rules:
- Be concrete, not vague. 'Logic steps' should be ordered actionable verbs.
- If the capability needs LLM calls, note which model.
- If it needs DB writes, specify tables.
- Don't invent capabilities outside Tony's actual infrastructure."""


CODER_PROMPT = """You are the Coder for Tony's capability builder. You have a spec. Write ONLY the Python code.

Spec:
{spec}

Rules:
- Start with: from fastapi import APIRouter, Depends
- Import: from app.core.security import verify_token
- Define: router = APIRouter()
- Every endpoint: _=Depends(verify_token)
- Use psycopg2 for DB (NOT asyncpg) — set sslmode="require"
- get_conn() helper pattern: psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
- Wrap DB calls in try/except, return {{"ok": False, "error": str(e)}} on failure
- Include CREATE TABLE IF NOT EXISTS for any tables you use (self-contained)
- Use httpx.AsyncClient for external HTTP
- British English in any user-facing strings
- NEVER add user_id (single-user system)
- NEVER mention CCJ, Western Circle, or legacy debt topics
- Keep it under 150 lines

Output ONLY the Python code. No markdown, no explanation."""


CRITIC_PROMPT = """You are the Critic for Tony's capability builder. Review this code against the spec. Be specific and harsh.

Spec:
{spec}

Code:
```python
{code}
```

Return STRICT JSON:
{{
  "issues": [
    {{"severity": "critical|high|medium|low", "location": "line X or function Y", "problem": "...", "fix": "..."}},
    ...
  ],
  "overall_rating": "ship_it|revise|reject",
  "summary": "one-line verdict"
}}

Check for:
- Missing auth on endpoints
- Unhandled DB errors
- Blocking synchronous calls in async functions
- Dict-vs-string type confusion (remember the memory bug)
- String format bugs with JSON examples (remember the fact extractor bug)
- Missing timezone handling with datetime
- References to non-existent functions
- Hardcoded Matthew facts that should be queried
- Over-confident responses (potential fabrication sources)
- Missing dedup/idempotency for stateful writes

If you see ZERO issues, say so — don't invent problems."""


REVISOR_PROMPT = """You are the Revisor for Tony's capability builder. Fix every issue the Critic raised.

Spec:
{spec}

Original code:
```python
{code}
```

Critique:
{critique}

Output the revised Python code. Fix every critical and high issue.
Medium issues: fix if straightforward. Low: only if fix is obvious.

Output ONLY the revised Python code. No markdown, no explanation."""


async def _call_gemini(prompt: str, max_tokens: int = 2000) -> Optional[str]:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from app.core import gemini_client
        resp = await gemini_client.generate_content(
            tier="flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"maxOutputTokens": max_tokens, "temperature": 0.2},
            timeout=60.0,
            caller_context="multi_agent_builder",
        )
        response = gemini_client.extract_text(resp)

        # Log the call for budget tracking
        try:
            from app.core.budget_guard import log_api_call
            log_api_call("gemini-2.5-flash", "multi_agent_build",
                         tokens=max_tokens, source="multi_agent_builder")
        except Exception:
            pass

        return response
    except Exception as e:
        print(f"[MULTI_AGENT] Gemini call failed: {e}")
        return None


def _strip_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        t = "\n".join(lines).strip()
    # Find outer {}
    first = t.find("{")
    last = t.rfind("}")
    if first < 0 or last < 0:
        return t
    return t[first:last+1]


def _strip_code(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        lines = [l for l in lines
                 if not l.strip().startswith("```")]
        t = "\n".join(lines).strip()
    return t


async def architect_phase(capability_name: str) -> Optional[Dict]:
    """Produce a spec."""
    prompt = ARCHITECT_PROMPT.format(capability_name=capability_name)
    response = await _call_gemini(prompt, max_tokens=1500)
    if not response:
        return None
    try:
        spec_json = _strip_json(response)
        return json.loads(spec_json)
    except Exception as e:
        print(f"[ARCHITECT] Parse failed: {e}")
        return None


async def coder_phase(spec: Dict) -> Optional[str]:
    """Produce code from spec."""
    prompt = CODER_PROMPT.format(spec=json.dumps(spec, indent=2))
    response = await _call_gemini(prompt, max_tokens=4000)
    if not response:
        return None
    return _strip_code(response)


async def critic_phase(spec: Dict, code: str) -> Optional[Dict]:
    """Review code against spec."""
    prompt = CRITIC_PROMPT.format(
        spec=json.dumps(spec, indent=2),
        code=code,
    )
    response = await _call_gemini(prompt, max_tokens=2000)
    if not response:
        return None
    try:
        return json.loads(_strip_json(response))
    except Exception as e:
        print(f"[CRITIC] Parse failed: {e}")
        return None


async def revisor_phase(spec: Dict, code: str, critique: Dict) -> Optional[str]:
    """Revise code based on critique."""
    # Only do revision if there are critical/high issues
    issues = critique.get("issues", [])
    critical_issues = [i for i in issues if i.get("severity") in ("critical", "high")]
    if not critical_issues:
        return code  # no revision needed

    prompt = REVISOR_PROMPT.format(
        spec=json.dumps(spec, indent=2),
        code=code,
        critique=json.dumps(critique, indent=2),
    )
    response = await _call_gemini(prompt, max_tokens=4000)
    if not response:
        return code  # fall back to original
    return _strip_code(response)


async def build_capability_multi_agent(capability_name: str) -> Dict:
    """
    Full multi-agent pipeline. Returns {ok, spec, code, critique, issues_fixed}.
    """
    # Budget check first
    try:
        from app.core.budget_guard import is_autonomous_allowed
        if not is_autonomous_allowed():
            return {"ok": False, "error": "Autonomous work is currently frozen by budget guard"}
    except Exception:
        pass

    # Phase 1: Architect
    spec = await architect_phase(capability_name)
    if not spec:
        return {"ok": False, "phase": "architect", "error": "Spec generation failed"}

    # Phase 2: Coder
    code = await coder_phase(spec)
    if not code:
        return {"ok": False, "phase": "coder", "error": "Code generation failed", "spec": spec}

    # Phase 3: Critic
    critique = await critic_phase(spec, code)
    if not critique:
        # Continue without critique if it fails — don't block the whole build
        critique = {"issues": [], "overall_rating": "ship_it",
                    "summary": "Critic unavailable"}

    # Phase 4: Revisor (only if critical issues)
    if critique.get("overall_rating") == "reject":
        return {"ok": False, "phase": "critic", "error": "Critic rejected the build",
                "spec": spec, "code": code, "critique": critique}

    final_code = await revisor_phase(spec, code, critique)
    issues_fixed = len([i for i in critique.get("issues", [])
                       if i.get("severity") in ("critical", "high")])

    # Phase 5: Final validation
    try:
        from app.core.capability_builder import validate_code, runtime_import_check
        val = validate_code(final_code)
        if not val.get("valid"):
            return {"ok": False, "phase": "final_validation",
                    "error": val.get("error"), "spec": spec, "code": final_code,
                    "critique": critique}

        rt = runtime_import_check(final_code, spec.get("name", "new_capability"))
        if not rt.get("ok"):
            return {"ok": False, "phase": "runtime_check",
                    "error": rt.get("error"), "spec": spec, "code": final_code,
                    "critique": critique}
    except Exception as e:
        print(f"[MULTI_AGENT] Validation phase error: {e}")

    return {
        "ok": True,
        "spec": spec,
        "code": final_code,
        "critique": critique,
        "issues_fixed": issues_fixed,
    }
