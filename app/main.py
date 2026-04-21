import os
import psycopg2
from fastapi import FastAPI, Request

def _one_time_ccj_cleanup_sync():
    """
    One-off cleanup: wipe Western Circle / CCJ from Tony's active memory.
    Matthew has asked repeatedly to stop mentioning it. The prompt rules weren't enough.
    Runs once per process startup. Idempotent — safe to run every boot.
    """
    import os
    import psycopg2
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.autocommit = True  # so failed statements (e.g. table-not-exist) don't abort subsequent ones
        cur = conn.cursor()

        # FIRST: wipe any push-fallback spam alerts that accumulated from the recursive loop bug
        try:
            cur.execute("""
                DELETE FROM tony_alerts
                WHERE source = 'tony_push' OR title LIKE '%Tony — Urgent%'
            """)
            if cur.rowcount > 0:
                print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} push-fallback spam alerts")
        except Exception as e:
            print(f"[STARTUP CLEANUP] Spam cleanup failed: {e}")

        # Mark Western Circle / CCJ / Cashfloat alerts as read + expired
        for topic in ["western circle", "ccj", "cashfloat"]:
            try:
                cur.execute("""
                    UPDATE tony_alerts
                    SET read = TRUE, expires_at = NOW() - INTERVAL '1 hour'
                    WHERE (title ILIKE %s OR body ILIKE %s OR source ILIKE %s)
                """, (f"%{topic}%", f"%{topic}%", f"%{topic}%"))
                print(f"[STARTUP CLEANUP] Cleared {cur.rowcount} {topic} alerts")
            except Exception as e:
                print(f"[STARTUP CLEANUP] Alert clear {topic} failed: {e}")

            try:
                cur.execute("""
                    INSERT INTO tony_topic_bans
                    (chat_session_id, topic, phrase_that_triggered, expires_at)
                    SELECT NULL, %s, 'one-time startup cleanup — Matthew asked repeatedly', NOW() + INTERVAL '30 days'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM tony_topic_bans
                        WHERE topic ILIKE %s AND active = TRUE
                        AND expires_at > NOW() + INTERVAL '7 days'
                    )
                """, (topic, topic))
            except Exception as e:
                print(f"[STARTUP CLEANUP] Ban {topic} failed: {e}")

            try:
                cur.execute("""
                    UPDATE tony_semantic_memory
                    SET importance = 0
                    WHERE content ILIKE %s AND importance > 0
                """, (f"%{topic}%",))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Demoted {cur.rowcount} {topic} memories")
            except Exception:
                pass

            try:
                cur.execute("""
                    UPDATE tony_goals
                    SET status = 'dormant'
                    WHERE (title ILIKE %s OR description ILIKE %s)
                    AND status NOT IN ('completed', 'dormant')
                """, (f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Dormant {cur.rowcount} {topic} goals")
            except Exception:
                pass

            # Also clear living memory rows that mention the topic
            try:
                cur.execute("""
                    DELETE FROM tony_living_memory
                    WHERE content ILIKE %s
                """, (f"%{topic}%",))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} living memory rows")
            except Exception:
                pass

            # Clear episodic memory rows that mention the topic
            try:
                cur.execute("""
                    DELETE FROM tony_episodic_memory
                    WHERE summary ILIKE %s OR content ILIKE %s
                """, (f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} episodic memory rows")
            except Exception:
                pass

            # Clear RAG chunks that mention the topic
            try:
                cur.execute("""
                    DELETE FROM rag_chunks
                    WHERE content ILIKE %s OR source ILIKE %s
                """, (f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} RAG chunks")
            except Exception:
                pass

            # Clear tony_cases rows
            try:
                cur.execute("""
                    DELETE FROM tony_cases
                    WHERE case_name ILIKE %s OR opponent ILIKE %s
                """, (f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} case rows")
            except Exception:
                pass

            # Clear living memory rows containing banned topic (will be re-seeded clean)
            try:
                cur.execute("""
                    DELETE FROM tony_living_memory
                    WHERE content ILIKE %s
                """, (f"%{topic}%",))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} living_memory rows (will re-seed clean)")
            except Exception as e:
                print(f"[STARTUP CLEANUP] living_memory delete {topic}: {e}")

            # Clear world_model rows
            try:
                cur.execute("""
                    DELETE FROM tony_world_model
                    WHERE content ILIKE %s
                """, (f"%{topic}%",))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} world_model rows")
            except Exception as e:
                print(f"[STARTUP CLEANUP] world_model delete {topic}: {e}")

            # Delete goals (not just dormant)
            try:
                cur.execute("""
                    DELETE FROM tony_goals
                    WHERE title ILIKE %s OR description ILIKE %s
                """, (f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] DELETED {cur.rowcount} {topic} goals")
            except Exception:
                pass

            # Delete correspondence emails
            try:
                cur.execute("""
                    DELETE FROM tony_correspondence
                    WHERE body ILIKE %s OR subject ILIKE %s OR from_party ILIKE %s
                """, (f"%{topic}%", f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} correspondence rows")
            except Exception:
                pass

            # Delete Gmail cache rows
            try:
                cur.execute("""
                    DELETE FROM tony_email_cache
                    WHERE subject ILIKE %s OR body ILIKE %s OR from_addr ILIKE %s
                """, (f"%{topic}%", f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} cached email rows")
            except Exception:
                pass

            # Delete tony_email_queue drafts  
            try:
                cur.execute("""
                    DELETE FROM tony_email_queue
                    WHERE subject ILIKE %s OR body ILIKE %s
                """, (f"%{topic}%", f"%{topic}%"))
                if cur.rowcount > 0:
                    print(f"[STARTUP CLEANUP] Deleted {cur.rowcount} {topic} email queue drafts")
            except Exception:
                pass

        conn.commit()
        cur.close()
        conn.close()
        print("[STARTUP CLEANUP] CCJ/Western Circle cleanup complete")
    except Exception as e:
        print(f"[STARTUP CLEANUP] Failed: {e}")


# CRITICAL: run CCJ cleanup BEFORE router imports so seeds re-init with clean data
try:
    _one_time_ccj_cleanup_sync()
except Exception as _cleanup_err:
    print(f"[STARTUP] Pre-router cleanup failed: {_cleanup_err}")

from app.api.v1.router import router as v1_router

app = FastAPI(title="Nova Backend", version="1.0.0")

app.include_router(v1_router, prefix="/api/v1")

import asyncio
from datetime import datetime

async def autonomous_loop():
    """
    Tony's fast 6-hour loop. Runs inside the web service.
    Handles time-sensitive work only — must not block chat:
    - Goal check-ins
    - Email scans and drafting
    - Proactive alerts
    - Goal execution
    - WhatsApp notifications

    Heavy deep-work tasks (learning synthesis, memory consolidation,
    strategic advisor, meta-cognition, code intelligence, etc.) run
    in the separate think_worker cron service at 01:00 UTC daily.
    """
    await asyncio.sleep(300)  # 5 min after startup to let things settle
    while True:
        try:
            print(f"[AUTONOMOUS] Fast loop starting at {datetime.utcnow().isoformat()}")

            # Fast proactive work only — no heavy jobs
            tasks = [
                ("tony_work_on_goals", "app.core.goals", "tony_work_on_goals"),
                ("run_proactive_scan", "app.core.proactive", "run_proactive_scan"),
                ("run_proactive_intelligence", "app.core.proactive_intelligence", "run_proactive_intelligence"),
                ("run_proactive_scheduling", "app.core.proactive_scheduler", "run_proactive_scheduling"),
                ("check_urgent_alerts", "app.core.whatsapp", "check_and_notify_urgent_alerts"),
                ("scan_for_actionable_emails", "app.core.email_agent", "scan_for_actionable_emails"),
                ("scan_and_draft_replies", "app.core.email_drafter", "scan_and_draft_replies"),
                ("run_goal_execution", "app.core.goal_executor", "run_goal_execution"),
                ("run_anticipation_engine", "app.core.anticipation_engine", "run_anticipation_engine"),
            ]

            for name, module_path, fn_name in tasks:
                try:
                    import importlib
                    mod = importlib.import_module(module_path)
                    fn = getattr(mod, fn_name)
                    await fn()
                except Exception as e:
                    print(f"[AUTONOMOUS] {name} failed: {e}")

            print("[AUTONOMOUS] Fast loop complete. Sleeping 6h.")
        except Exception as e:
            print(f"[AUTONOMOUS] Loop error: {e}")
        await asyncio.sleep(6 * 3600)  # Every 6 hours



@app.on_event("startup")
async def startup_event():
    # Cleanup now runs synchronously at import time (see below) — no task needed here
    asyncio.create_task(autonomous_loop())
    # Background task queue worker — lets Tony run long-horizon tasks
    try:
        from app.core.task_queue import worker_loop
        from app.core.task_handlers import register_all_handlers, schedule_daily_evals
        from app.core.scheduled_briefings import register_brief_handler, schedule_todays_briefs
        from app.core.email_monitor import register_monitor as register_email_monitor
        register_all_handlers()
        register_brief_handler()
        register_email_monitor()
        asyncio.create_task(worker_loop(poll_interval_seconds=10))
        # Queue a daily eval run if one isn't already scheduled
        schedule_daily_evals()
        # Queue today's scheduled briefs if not already done
        schedule_todays_briefs()
    except Exception as e:
        print(f"[STARTUP] Task queue setup failed: {e}")
    print("[STARTUP] Tony autonomous loop started")

    # Migrate existing memories to semantic index on first run
    async def _migrate():
        try:
            from app.core.semantic_memory import migrate_existing_memories
            await migrate_existing_memories()
        except Exception as e:
            print(f"[STARTUP] Semantic migration failed: {e}")
    asyncio.create_task(_migrate())

    # Deduplicate memories on startup
    async def _dedup():
        await asyncio.sleep(30)  # Wait for startup to settle
        try:
            from app.core.memory import deduplicate_memories
            await deduplicate_memories()
        except Exception as e:
            print(f"[STARTUP] Memory dedup failed: {e}")
    asyncio.create_task(_dedup())

    # Run self-repair cycle on startup
    async def _self_repair():
        await asyncio.sleep(60)  # After everything settles
        try:
            from app.core.self_repair import run_self_repair_cycle
            result = await run_self_repair_cycle()
            print(f"[STARTUP] Self-repair: {result.get('health', {}).get('overall', 'unknown')}")
        except Exception as e:
            print(f"[STARTUP] Self-repair failed: {e}")
    asyncio.create_task(_self_repair())

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

    # Phase 4a: Tony works on Matthew's goals autonomously
    try:
        from app.core.goals import tony_work_on_goals
        goal_results = await tony_work_on_goals()
        db_log("goal_work", f"Worked on {len(goal_results)} goals")
    except Exception as e:
        db_log("goal_work_failed", str(e))

    # Phase 4b: Tony runs proactive scan — emails, legal, deadlines
    try:
        from app.core.proactive import run_proactive_scan
        scan_result = await run_proactive_scan()
        db_log("proactive_scan", f"Alerts created: {scan_result.get('alerts_created',0)}")
    except Exception as e:
        db_log("proactive_scan_failed", str(e))

    # Phase 5: Tony decides what to build and builds it autonomously
    improvement = {}
    try:
        from app.core.tony_mission import run_autonomous_improvement
        improvement = await run_autonomous_improvement()
        db_log("autonomous_improvement", f"Built: {improvement.get('built','nothing')} — {improvement.get('reason','')}")
    except Exception as e:
        db_log("autonomous_improvement_failed", str(e))

    # Phase 6: Log completion
    summary = {
        "status": "completed",
        "timestamp": datetime.utcnow().isoformat(),
        "files_checked": len(codebase),
        "syntax_errors": len(errors),
        "frontend_build": build_status,
        "apk_url": apk_url,
        "autonomous_improvement": improvement.get("status", "skipped"),
        "capability_built": improvement.get("built"),
    }
    db_log("loop_complete", str(summary))
    return summary
