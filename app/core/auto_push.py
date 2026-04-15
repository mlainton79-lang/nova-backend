import re
import httpx
import os
import base64

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


async def get_github_file(file_path: str, repo: str, branch: str) -> tuple:
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}?ref={branch}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return None, None
            data = resp.json()
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            return content, data.get("sha")
    except Exception:
        return None, None


async def push_github_file(file_path: str, content: str, commit_message: str, repo: str, branch: str) -> bool:
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            existing = await client.get(f"{url}?ref={branch}", headers=headers)
            sha = existing.json().get("sha") if existing.status_code == 200 else None
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            payload = {"message": commit_message, "content": encoded, "branch": branch}
            if sha:
                payload["sha"] = sha
            resp = await client.put(url, headers=headers, json=payload)
            return resp.status_code in (200, 201)
    except Exception as e:
        print(f"[AUTO_PUSH] push error: {e}")
        return False


async def process_auto_push(reply: str) -> tuple:
    cleaned_reply = reply
    push_results = []
    stripped = strip_code_fences(reply)

    BACKEND_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")
    BACKEND_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
    FRONTEND_REPO = os.environ.get("FRONTEND_REPO", "mlainton79-lang/nova-android")
    FRONTEND_BRANCH = os.environ.get("FRONTEND_BRANCH", "master")

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
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***BLOCKED: {file_path} is protected.***")
            continue

        try:
            repo = FRONTEND_REPO if is_frontend_file(file_path) else BACKEND_REPO
            branch = FRONTEND_BRANCH if is_frontend_file(file_path) else BACKEND_BRANCH
            current_content, sha = await get_github_file(file_path, repo, branch)

            if current_content is None:
                push_results.append({"file_path": file_path, "ok": False, "error": "Could not fetch file"})
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH failed: could not fetch {file_path}***")
                continue

            new_content, matched = find_and_replace_normalised(current_content, find_text, replace_text)
            if not matched:
                push_results.append({"file_path": file_path, "ok": False, "error": "FIND text not found"})
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH failed: could not find text in {file_path}***")
                continue

            success = await push_github_file(file_path, new_content, commit_message, repo, branch)
            push_results.append({"file_path": file_path, "ok": success, "repo": "frontend" if is_frontend_file(file_path) else "backend"})
            if success:
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***Patched {file_path}.***")
            else:
                cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH push failed for {file_path}***")
        except Exception as e:
            push_results.append({"file_path": file_path, "ok": False, "error": str(e)})
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***PATCH failed: {str(e)}***")

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
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***BLOCKED: {file_path} is protected.***")
            continue

        try:
            repo = FRONTEND_REPO if is_frontend_file(file_path) else BACKEND_REPO
            branch = FRONTEND_BRANCH if is_frontend_file(file_path) else BACKEND_BRANCH
            success = await push_github_file(file_path, content, commit_message, repo, branch)
            push_results.append({"file_path": file_path, "ok": success, "repo": "frontend" if is_frontend_file(file_path) else "backend"})
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***Pushed {file_path}.***")
        except Exception as e:
            push_results.append({"file_path": file_path, "ok": False, "error": str(e)})
            cleaned_reply = cleaned_reply.replace(match.group(0), f"***Push failed: {str(e)}***")

    frontend_pushes = [p for p in push_results if p.get("repo") == "frontend" and p.get("ok")]
    if frontend_pushes:
        cleaned_reply += f"\n\n***Pushed {len(frontend_pushes)} frontend file(s). GitHub Actions will build a new APK.***"

    return cleaned_reply, push_results
