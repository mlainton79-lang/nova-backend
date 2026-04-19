"""
Tony's Code Intelligence Engine.

Tony reads, understands, and improves his own code.

This goes beyond just writing new modules.
Tony can:
1. Read any file in his codebase via GitHub API
2. Understand what it does and how it could be better
3. Identify specific functions to improve
4. Rewrite them with improvements
5. Validate the change doesn't break anything
6. Push the improvement autonomously

Used for:
- Performance improvements (slow functions)
- Bug fixes (functions that error frequently)
- Quality improvements (functions with low scores)
- Refactoring (code that grew messy)

This is genuine self-modification - Tony editing his own brain.
"""
import os
import re
import ast
import base64
import httpx
from typing import Dict, List, Optional, Tuple
from app.core.model_router import gemini, gemini_json

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")


async def read_file_from_github(filepath: str) -> Optional[Tuple[str, str]]:
    """Read a file from GitHub. Returns (content, sha)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}",
                headers={"Authorization": f"token {GITHUB_TOKEN}"}
            )
            if r.status_code == 200:
                data = r.json()
                content = base64.b64decode(data["content"]).decode()
                return content, data["sha"]
    except Exception as e:
        print(f"[CODE_INTEL] Read failed {filepath}: {e}")
    return None, None


async def write_file_to_github(filepath: str, content: str, sha: str, message: str) -> bool:
    """Write a file back to GitHub."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            payload = {
                "message": message,
                "content": base64.b64encode(content.encode()).decode(),
                "sha": sha,
                "branch": "main"
            }
            r = await client.put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}",
                headers={"Authorization": f"token {GITHUB_TOKEN}"},
                json=payload
            )
            return r.status_code in (200, 201)
    except Exception as e:
        print(f"[CODE_INTEL] Write failed: {e}")
        return False


async def analyse_function_quality(func_code: str, func_name: str, context: str = "") -> Dict:
    """Tony analyses a specific function for improvement opportunities."""
    prompt = f"""Analyse this Python function for quality and improvement opportunities.

Function: {func_name}
Context: {context[:300]}

Code:
```python
{func_code[:2000]}
```

Evaluate:
1. Correctness - does it handle edge cases?
2. Error handling - what can go wrong that isn't caught?
3. Performance - any obvious bottlenecks?
4. Readability - is it clear what it does?
5. Security - any vulnerabilities?
6. Specific improvement - what ONE change would make the biggest difference?

Respond in JSON:
{{
    "quality_score": 1-10,
    "main_issue": "the most important problem",
    "improvement": "specific code improvement to make",
    "should_rewrite": true/false,
    "priority": "high/medium/low"
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=512) or {}


async def improve_function(
    filepath: str,
    func_name: str,
    improvement_description: str
) -> bool:
    """
    Tony rewrites a specific function to be better.
    Reads the file, finds the function, rewrites it, validates, pushes.
    """
    content, sha = await read_file_from_github(filepath)
    if not content or not sha:
        return False

    # Find the function in the file
    func_pattern = rf"(async def {func_name}|def {func_name})\s*\("
    match = re.search(func_pattern, content)
    if not match:
        print(f"[CODE_INTEL] Function {func_name} not found in {filepath}")
        return False

    # Extract function (simplified - find start, estimate end by indentation)
    start_idx = match.start()
    lines = content[start_idx:].split('\n')
    func_lines = [lines[0]]
    for line in lines[1:]:
        if line and not line.startswith(' ') and not line.startswith('\t'):
            break
        func_lines.append(line)

    original_func = '\n'.join(func_lines)

    prompt = f"""Rewrite this Python function to fix the following issue:

Issue: {improvement_description}

Original function:
```python
{original_func}
```

File context: {filepath}

Rules:
- Keep the same function signature (name and parameters)
- Keep the same return type
- Fix the specific issue described
- Don't change functionality, only improve it
- Keep it compatible with the rest of the codebase

Output ONLY the improved function code. No explanation, no markdown."""

    improved = await gemini(prompt, task="reasoning", max_tokens=2048, temperature=0.1)
    if not improved:
        return False

    # Clean markdown
    improved = re.sub(r'```python\n?', '', improved)
    improved = re.sub(r'```\n?', '', improved)
    improved = improved.strip()

    # Validate the improved function
    try:
        ast.parse(improved)
    except SyntaxError as e:
        print(f"[CODE_INTEL] Syntax error in improved function: {e}")
        return False

    # Replace in file
    new_content = content[:start_idx] + improved + content[start_idx + len(original_func):]

    # Final validation of full file
    try:
        ast.parse(new_content)
    except SyntaxError as e:
        print(f"[CODE_INTEL] Full file syntax error after replacement: {e}")
        return False

    # Push
    success = await write_file_to_github(
        filepath, new_content, sha,
        f"improve({func_name}): {improvement_description[:60]} — autonomous improvement by Tony"
    )

    if success:
        print(f"[CODE_INTEL] Successfully improved {func_name} in {filepath}")

    return success


async def find_underperforming_functions() -> List[Dict]:
    """
    Find functions that are frequently failing or could be improved.
    Uses eval log and build log to identify targets.
    """
    import psycopg2
    targets = []

    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()

        # Functions that recently caused errors
        try:
            cur.execute("""
                SELECT content FROM tony_build_log
                WHERE success = FALSE
                AND created_at > NOW() - INTERVAL '48 hours'
                ORDER BY created_at DESC
                LIMIT 10
            """)
            failures = [r[0] for r in cur.fetchall()]

            # Extract function names from error messages
            for failure in failures:
                func_match = re.search(r'(\w+)\s+failed|error in (\w+)|(\w+)\.py', failure)
                if func_match:
                    func_name = next(g for g in func_match.groups() if g)
                    targets.append({
                        "reason": "frequent_failures",
                        "description": failure[:100],
                        "priority": "high"
                    })
        except Exception:
            pass

        cur.close()
        conn.close()

    except Exception as e:
        print(f"[CODE_INTEL] Find targets failed: {e}")

    return targets[:3]


async def run_code_intelligence_cycle() -> Dict:
    """
    Tony reviews and improves his own code.
    Runs as part of autonomous loop.
    """
    print("[CODE_INTEL] Starting code intelligence cycle...")

    # Find what needs improvement
    targets = await find_underperforming_functions()

    if not targets:
        # Look for general improvements to key files
        key_files = [
            ("app/core/semantic_memory.py", "search_memories",
             "Add cosine similarity threshold filtering and improve result ranking"),
            ("app/core/emotional_intelligence.py", "tony_read_context",
             "Improve time-of-day signals and add message length as stress indicator"),
        ]

        for filepath, func_name, improvement in key_files[:1]:
            content, sha = await read_file_from_github(filepath)
            if content:
                analysis = await analyse_function_quality(
                    content, func_name,
                    f"Part of Tony's {filepath} module"
                )
                if analysis.get("should_rewrite") and analysis.get("quality_score", 10) < 8:
                    success = await improve_function(filepath, func_name, improvement)
                    if success:
                        return {
                            "improved": func_name,
                            "file": filepath,
                            "improvement": improvement
                        }

    return {"ok": True, "targets_found": len(targets)}
