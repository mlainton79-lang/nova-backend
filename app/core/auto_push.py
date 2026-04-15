import asyncio
import traceback
import re
import httpx
import os
import base64
from app.api.v1.endpoints.code_edit import get_file_from_github, push_file_to_github

PUSH_PATTERN = re.compile(
    r'\[\[\[PUSH:(.+?)\|(.+?)\]\]\](.*?)\[\[\[/PUSH\]\]\]',
    re.DOTALL
)

PATCH_PATTERN = re.compile(
    r'\[\[\[PATCH:(.+?)\|(.+?)\]\]\]\s*<<<FIND>>>\s*(.*?)\s*<<<REPLACE>>>\s*(.*?)\s*\[\[\[/PATCH\]\]\]',
    re.DOTALL
)

PROTECTED_FILES = [
    'app/providers/claude_adapter.py',
    'app/providers/gemini_adapter.py',
    'app/providers/openai_adapter.py',
    'app/providers/council.py',
    'app/core/config.py',
    'app/core/security.py',
    'app/core/auto_push.py',
    'app/main.py',
    'Procfile',
    'requirements.txt',
]

FRONTEND_EXTENSIONS = ('.kt', '.xml', '.gradle', '.properties', '.yml')
FRONTEND_PATHS = ('app/src/main/', '.github/')


def is_frontend_file(file_path: str) -> bool:
    return (
        any(file_path.startswith(p) for p in FRONTEND_PATHS) or
        any(file_path.endswith(e) for e in FRONTEND_EXTENSIONS)
    ) and not file_path.endswith('.py')


def strip_code_fences(text: str) -> str:
    return re.sub(r'```.*?```', '', text, flags=re.DOTALL)


def normalise_whitespace(text: str) -> str:
    lines = text.splitlines()
    stripped = [line.strip() for line in lines]
    return '\n'.join(stripped)


def find_and_replace_normalised(content: str, find_text: str, replace_text: str) -> tuple:
    if find_text in content:
        return content.replace(find_text, replace_text, 1), True

    find_normalised = normalise_whitespace(find_text)
    content_lines = content.splitlines()
    find_lines = find_normalised.splitlines()
    n = len(find_lines)

    for i in range(len(content_lines) - n + 1):
        window = [line.strip() for line in content_lines[i:i + n]]
        if window == find_lines:
            original_block = '\n'.join(content_lines[i:i + n])
            return content.replace(original_block, replace_text, 1), True

    return content, False


async def get_frontend_file_content(file_path: str) -> tuple:
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    FRONTEND_REPO = os.environ.get("FRONTEND_REPO", "mlainton79-lang/nova-android")
    FRONTEND_BRANCH = os.environ.get("FRONTEND_BRANCH", "master")
    GITHUB_API = "https://api.github.com"

    url = f"{GITHUB_API}/repos/{FRONTEND_REPO}/contents/{file_path}?ref={FRONTEND_BRANCH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return None, None
            data = resp.json()
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            sha = data.get("sha")
            return content, sha
    except Exception:
        return None, None


async def push_frontend_to_github(file_path: str, content: str, commit_message: str) -> bool:
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    FRONTEND_REPO = os.environ.get("FRONTEND_REPO", "mlainton79-lang/nova-android")
    FRONTEND_BRANCH = os.environ.get("FRONTEND_BRANCH", "master")
    GITHUB_API = "https://api.github.com"

    url = f"{GITHUB_API}/repos/{FRONTEND_REPO}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            existing = await client.get(f"{url}?ref={FRONTEND_BRANCH}", headers=headers)
            sha = existing.json().get("sha") if existing.status_code == 200 else None

            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            payload = {
                "message": commit_message,
                "content": encoded,
                "branch": FRONTEND_BRANCH
            }
            if sha:
                payload["sha"] = sha

            resp = await client.put(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                print(f"[AUTO_PUSH] Frontend push successful: {file_path}")
                return True
            else:
                print(f"[AUTO_PUSH] Frontend push failed ({resp.status_code}): {resp.text[:200]}")
                return False
    except Exception as e:
        print(f"[AUTO_PUSH] Frontend push error: {str(e)}")
        return False


async def process_auto_push(reply: str) -> tuple:
    cleaned_reply = reply
    push_results = []
    stripped = strip_code_fences(reply)

    patch_markers = list(PATCH_PATTERN.finditer(stripped))
    valid_patch_paths = set(m.group(1).strip() for m in patch_markers)

    for match in PATCH_PATTERN.finditer(reply):
        file_path = match.group(1).strip()
        commit_message = match.group(2).strip()
        find_text = match.group(3).strip()
        replace_text = match.group(4).strip()

        if file_path not in valid_patch_paths:
            continue

        if any(file_path == p or file_path.endswith('/' + p) for p in PROTECTED_FILES):
            push_results.append({"file_path": file_path, "ok": False, "error": "Protected file"})
            cleaned_reply = cleaned_reply.replace(
                match.group(0),
                f"***BLOCKED: {file_path} is a protected file.***"
            )
            continue

        try:
            if is_frontend_file(file_path):
                current_content, _ = await get_frontend_file_content(file_path)
            else:
                try:
                    current_content, _ = await get_file_from_github(file_path)
                except Exception:
                    current_content = None

            if current_content is None:
                push_results.append({"file_path": file_path, "ok": False, "error": "Could not fetch current file"})
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH failed for {file_path}: could not fetch current file***")
                continue

            new_content, matched = find_and_replace_normalised(current_content, find_text, replace_text)

            if not matched:
                push_results.append({"file_path": file_path, "ok": False, "error": "FIND text not found in file"})
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH failed for {file_path}: could not find the text to replace***")
                continue

            if is_frontend_file(file_path):
                success = await push_frontend_to_github(file_path, new_content, commit_message)
            else:
                _, sha = await get_file_from_github(file_path)
                success = await push_file_to_github(file_path, new_content, sha, commit_message)

            repo = "frontend" if is_frontend_file(file_path) else "backend"
            push_results.append({"file_path": file_path, "ok": success, "repo": repo})
            if success:
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***Patched and pushed {file_path} to {repo} repo.***")
            else:
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH push failed for {file_path}***")

        except Exception as e:
            push_results.append({"file_path": file_path, "ok": False, "error": str(e)})
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH failed for {file_path}: {str(e)}***")

    full_markers = list(PUSH_PATTERN.finditer(stripped))
    valid_paths = set(m.group(1).strip() for m in full_markers)

    for match in PUSH_PATTERN.finditer(reply):
        file_path = match.group(1).strip()
        commit_message = match.group(2).strip()
        content = match.group(3).strip()

        if file_path not in valid_paths:
            continue

        if any(file_path == p or file_path.endswith('/' + p) for p in PROTECTED_FILES):
            push_results.append({"file_path": file_path, "ok": False, "error": "Protected file"})
            cleaned_reply = cleaned_reply.replace(
                match.group(0),
                f"***BLOCKED: {file_path} is a protected file.***"
            )
            continue

        if is_frontend_file(file_path) and len(content) < 5000:
            try:
                from app.core.tool_registry import execute_read_frontend_file
                existing = await execute_read_frontend_file(file_path)
                if existing.get('ok') and existing.get('size', 0) > 5000:
                    push_results.append({"file_path": file_path, "ok": False, "error": "File too large for full PUSH", "repo": "frontend"})
                    cleaned_reply = cleaned_reply.replace(match.group(0), f"***BLOCKED: {file_path} is too large for full replacement. Use PATCH markers.***")
                    continue
            except Exception:
                pass

        try:
            if is_frontend_file(file_path):
                success = await push_frontend_to_github(file_path, content, commit_message)
                repo = "frontend"
            else:
                sha = None
                try:
                    _, sha = await get_file_from_github(file_path)
                except Exception:
                    sha = None
                success = await push_file_to_github(file_path, content, sha, commit_message)
                repo = "backend"

            push_results.append({"file_path": file_path, "ok": success, "repo": repo})
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***Pushed {file_path} to {repo} repo.***")

        except Exception as e:
            push_results.append({"file_path": file_path, "ok": False, "error": str(e)})
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***Push failed for {file_path}: {str(e)}***")

    frontend_pushes = [p for p in push_results if p.get("repo") == "frontend" and p.get("ok")]
    if frontend_pushes:
        cleaned_reply += f"\n\n***Pushed {len(frontend_pushes)} frontend file(s). GitHub Actions will build a new APK.***"

    return cleaned_reply, push_results
