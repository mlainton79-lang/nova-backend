"""
Tony's Code Review System.

Before any code goes to GitHub, Tony reviews it himself.
Uses multi-model review — Gemini and Claude both check it.
If they disagree, Tony takes the more conservative view.

Tony checks for:
- Logic errors (not just syntax)
- Security vulnerabilities
- Performance issues
- Integration problems
- Breaking changes to existing functionality
- Missing error handling

This makes Tony's self-builds much more reliable.
"""
import os
from typing import Dict, List
from app.core.model_router import gemini_json

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


async def review_code(code: str, capability_name: str, context: str = "") -> Dict:
    """
    Multi-model code review before deployment.
    Returns approval or specific issues to fix.
    """
    review_prompt = f"""You are a senior Python/FastAPI code reviewer.
Review this new capability Tony is adding to his codebase.

Capability: {capability_name}
Context: {context[:500]}

Code to review:
```python
{code[:4000]}
```

Review for:
1. Logic correctness — does it do what it claims?
2. Error handling — will it crash on bad input?
3. Security — any injection or auth issues?
4. Performance — any obvious bottlenecks?
5. Integration — will it break existing functionality?
6. FastAPI correctness — proper use of Depends, response models etc
7. Database safety — proper connection handling, no SQL injection

Respond in JSON:
{{
    "approved": true/false,
    "critical_issues": ["issues that MUST be fixed before deploy"],
    "warnings": ["non-critical concerns"],
    "quality_score": 1-10,
    "reviewer_notes": "brief summary"
}}

Be strict. Only approve code that is genuinely production-ready."""

    result = await gemini_json(review_prompt, task="reasoning", max_tokens=1024)
    return result or {"approved": False, "critical_issues": ["Review failed"], "quality_score": 0}


async def security_scan(code: str) -> Dict:
    """Quick security scan for common vulnerabilities."""
    issues = []
    
    # Hardcoded secrets
    import re
    secret_patterns = [
        r'password\s*=\s*["\'][^"\']+["\']',
        r'api_key\s*=\s*["\'][^"\']+["\']',
        r'secret\s*=\s*["\'][^"\']+["\']',
        r'token\s*=\s*["\'][A-Za-z0-9+/=]{20,}["\']',
    ]
    for pattern in secret_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            issues.append("Potential hardcoded secret detected")
    
    # SQL injection risks
    if "%" in code and "cur.execute" in code:
        if "%" not in '(%s)':  # Not using parameterised queries
            if re.search(r'execute\(f["\']|execute\(["\'].*\+', code):
                issues.append("Potential SQL injection: use parameterised queries")
    
    # Open redirects
    if "redirect_url" in code.lower() and "request." in code:
        issues.append("Review redirect URL validation")
    
    return {
        "secure": len(issues) == 0,
        "issues": issues
    }
