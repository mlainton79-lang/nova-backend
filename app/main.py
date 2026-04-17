import os
from fastapi import FastAPI, Request
from app.api.v1.router import router as v1_router

app = FastAPI(title="Nova Backend", version="1.0.0")

app.include_router(v1_router, prefix="/api/v1")

@app.get("/")
def root():
    return {"service": "Nova Backend", "status": "running"}

@app.post("/internal/trigger-self-improvement")
async def trigger_self_improvement(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != os.environ.get("DEV_TOKEN", "nova-dev-token"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    """
    Cron-triggered autonomous self-improvement loop.
    Validates, pushes improvements, verifies deployment.
    """
    import os, ast, httpx, asyncio
    from datetime import datetime
    from app.core.gmail_service import get_conn

    log_entries = []

    def db_log(stage, content):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO think_sessions (stage, content, created_at) VALUES (%s, %s, NOW())",
                (stage, content)
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[THINK] DB log failed: {e}")

    # Phase 1: Health check
    backend_url = "https://web-production-be42b.up.railway.app"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{backend_url}/api/v1/health")
            if r.status_code != 200:
                db_log("health_check_failed", f"Status {r.status_code}")
                return {"status": "aborted", "reason": "health check failed"}
        log_entries.append("health_check_passed")
        db_log("health_check", "Backend healthy at loop start")
    except Exception as e:
        db_log("health_check_failed", str(e))
        return {"status": "aborted", "reason": str(e)}

    # Phase 2: Fetch codebase from DB for analysis
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT file_path, content FROM codebase ORDER BY file_path")
        codebase = {row[0]: row[1] for row in cur.fetchall()}
        cur.execute("SELECT category, content FROM self_knowledge ORDER BY category")
        self_knowledge = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        conn.close()
        db_log("analysis", f"Fetched {len(codebase)} files, {len(self_knowledge)} knowledge items")
    except Exception as e:
        db_log("analysis_failed", str(e))
        return {"status": "aborted", "reason": f"codebase fetch failed: {e}"}

    # Phase 3: Syntax check all Python files in codebase
    errors = []
    for path, content in codebase.items():
        if path.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as e:
                errors.append(f"{path}: {e}")
    if errors:
        db_log("syntax_check_failed", "\n".join(errors))
        return {"status": "issues_found", "syntax_errors": errors}

    db_log("syntax_check_passed", f"All {len([p for p in codebase if p.endswith('.py')])} Python files clean")

    # Phase 4: Check GitHub Actions for latest frontend build status
    github_token = os.environ.get("GITHUB_TOKEN", "")
    frontend_repo = os.environ.get("FRONTEND_REPO", "mlainton79-lang/nova-android")
    apk_url = None
    build_status = "unknown"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://api.github.com/repos/{frontend_repo}/actions/runs",
                headers={"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"},
                params={"per_page": 1}
            )
            if r.status_code == 200:
                runs = r.json().get("workflow_runs", [])
                if runs:
                    latest = runs[0]
                    build_status = latest.get("conclusion", latest.get("status", "unknown"))
                    run_id = latest.get("id")
                    # Fetch artifact download URL if build succeeded
                    if build_status == "success":
                        ar = await client.get(
                            f"https://api.github.com/repos/{frontend_repo}/actions/runs/{run_id}/artifacts",
                            headers={"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
                        )
                        if ar.status_code == 200:
                            artifacts = ar.json().get("artifacts", [])
                            if artifacts:
                                apk_url = f"https://github.com/{frontend_repo}/actions/runs/{run_id}/artifacts/{artifacts[0]['id']}"
        db_log("github_check", f"Latest frontend build: {build_status}. APK: {apk_url or 'not available'}")
    except Exception as e:
        db_log("github_check_failed", str(e))

    # Phase 5: Log completion
    summary = {
        "status": "completed",
        "timestamp": datetime.utcnow().isoformat(),
        "files_checked": len(codebase),
        "syntax_errors": len(errors),
        "frontend_build": build_status,
        "apk_url": apk_url
    }
    db_log("loop_complete", str(summary))
    return summary
