"""
Eval Gate — runs regression tests against the live deployment after Tony pushes
autonomous code changes. If evals fail, Tony self-reverts the commit.

This is the safety layer that makes autonomous building safe enough to run
without your supervision.
"""
import os
import asyncio
import httpx
from typing import Dict


async def wait_for_railway_deploy(max_wait_seconds: int = 180) -> bool:
    """
    Poll the health endpoint until it responds, up to max_wait_seconds.
    Railway usually deploys in 60-120s.
    Returns True if the service is responding, False if timeout.
    """
    base = os.environ.get("TONY_BASE_URL",
        "https://web-production-be42b.up.railway.app").rstrip("/")
    token = os.environ.get("DEV_TOKEN", "nova-dev-token")

    for attempt in range(max_wait_seconds // 5):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{base}/api/v1/health",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(5)
    return False


async def run_eval_gate(critical_only: bool = True) -> Dict:
    """
    Run evals post-deploy. If critical tests fail, returns {"passed": False}.
    Used by autonomous builder to decide whether a commit is safe.
    """
    try:
        from app.evals.runner import run_all
        summary = await run_all(endpoint="chat")

        # "Critical" = categories we will NEVER allow regressions in
        critical_categories = {"voice", "ccj_isolation", "honesty"}

        if critical_only:
            critical_failures = [
                r for r in summary["results"]
                if not r["passed"] and r.get("category") in critical_categories
            ]
            passed = len(critical_failures) == 0
            return {
                "passed": passed,
                "summary": summary,
                "critical_failures": critical_failures,
            }
        else:
            return {
                "passed": summary["passed"] == summary["total"],
                "summary": summary,
            }
    except Exception as e:
        # If evals themselves crash, fail closed — don't promote
        return {"passed": False, "error": f"Eval runner crashed: {e}"}


async def revert_last_commit() -> Dict:
    """Revert the most recent commit on main. Used when eval gate fails."""
    import base64
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get current HEAD
            r = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO}/commits?per_page=2",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Failed to fetch commits: {r.status_code}"}
            commits = r.json()
            if len(commits) < 2:
                return {"ok": False, "error": "Not enough history to revert"}

            target_sha = commits[1]["sha"]  # second-most-recent = revert target

            # Force-update main to the previous commit
            r2 = await client.patch(
                f"https://api.github.com/repos/{GITHUB_REPO}/git/refs/heads/main",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
                json={"sha": target_sha, "force": True}
            )
            if r2.status_code in (200, 201):
                return {"ok": True, "reverted_to": target_sha[:7]}
            return {"ok": False, "error": f"Force update failed: {r2.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def post_deploy_check_and_revert_if_needed() -> Dict:
    """
    Full post-deploy safety check:
    1. Wait for Railway to finish deploying
    2. Run eval gate on critical categories
    3. If critical tests fail, revert the last commit
    Returns a report of what happened.
    """
    report = {"steps": []}

    # 1. Wait for deploy
    print("[EVAL_GATE] Waiting for Railway deploy...")
    ready = await wait_for_railway_deploy(max_wait_seconds=180)
    report["steps"].append({"step": "wait_for_deploy", "ok": ready})
    if not ready:
        report["action"] = "Timed out waiting for deploy — not reverting, but alerting"
        return report

    # 2. Run evals
    print("[EVAL_GATE] Running critical eval suite...")
    eval_result = await run_eval_gate(critical_only=True)
    report["steps"].append({
        "step": "evals",
        "ok": eval_result.get("passed", False),
        "summary": eval_result.get("summary", {}).get("pass_rate"),
    })

    if eval_result.get("passed"):
        report["action"] = "Deploy passed evals — promoting"
        return report

    # 3. Failed — revert
    print("[EVAL_GATE] Evals failed, reverting...")
    revert_result = await revert_last_commit()
    report["steps"].append({"step": "revert", "ok": revert_result.get("ok"),
                            "detail": revert_result})
    report["action"] = "Reverted last commit due to failed evals"

    # 4. Alert Matthew
    try:
        from app.core.proactive import create_alert
        failures = eval_result.get("critical_failures", [])
        failure_summary = "; ".join(f["id"] for f in failures[:5])
        create_alert(
            alert_type="eval_gate",
            title="Auto-revert: build failed evals",
            body=f"Tony's last push broke {len(failures)} critical tests ({failure_summary}). Commit has been reverted.",
            priority="high",
            source="eval_gate",
            expires_hours=48,
        )
    except Exception:
        pass

    return report
