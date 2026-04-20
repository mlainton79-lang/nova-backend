"""
Tony's Daily Deep-Work Worker.

Runs once daily at 01:00 UTC on Railway.
Handles the heavy, time-consuming jobs that would slow down chat if they
ran in the web service.

The web service's 6-hour loop handles fast proactive work:
- Email scans, alert creation, goal check-ins, short memory updates

This worker handles the deep thinking:
- Weekly learning synthesis (rewrites Tony's behaviour rules from 7 days of conversations)
- Memory consolidation (merges duplicates, promotes patterns, archives stale)
- Strategic weekly assessment (Tony's honest review of Matthew's life trajectory)
- Daily journal reflection (Tony's private thoughts on the day)
- Deep pattern analysis (7-day rhythm detection)
- Self-repair cycle (audit systems, flag real issues)
- Meta-cognition (Tony thinks about his own thinking, detects drift)
- Code intelligence (review and improve own functions)
- Income intelligence (deeper research on resale opportunities)
- Financial intelligence (full scan of email history)
- Relationship intelligence (family milestones, upcoming dates)

Each task logs to tony_worker_log so we can see what ran and what failed.
Any single task failing does not stop the others.
"""
import os
import sys
import asyncio
import traceback
from datetime import datetime

# Make app imports work
sys.path.insert(0, "/app")


async def _safe_run(name: str, fn, *args, **kwargs):
    """Run a task, log outcome, never raise."""
    start = datetime.utcnow()
    try:
        print(f"[WORKER] ▶ {name} starting at {start.isoformat()}")
        result = await fn(*args, **kwargs) if asyncio.iscoroutinefunction(fn) else fn(*args, **kwargs)
        duration = (datetime.utcnow() - start).total_seconds()
        print(f"[WORKER] ✓ {name} completed in {duration:.1f}s")
        _log_task(name, True, duration, str(result)[:300] if result else "")
        return result
    except Exception as e:
        duration = (datetime.utcnow() - start).total_seconds()
        tb = traceback.format_exc()[:500]
        print(f"[WORKER] ✗ {name} failed after {duration:.1f}s: {e}")
        print(tb)
        _log_task(name, False, duration, f"{e}\n{tb}")
        return None


def _log_task(name: str, success: bool, duration: float, detail: str):
    """Log task outcome to DB for later inspection."""
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_worker_log (
                id SERIAL PRIMARY KEY,
                task_name TEXT NOT NULL,
                success BOOLEAN,
                duration_seconds FLOAT,
                detail TEXT,
                ran_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute(
            "INSERT INTO tony_worker_log (task_name, success, duration_seconds, detail) VALUES (%s, %s, %s, %s)",
            (name, success, duration, detail[:2000])
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[WORKER] Log failed: {e}")


async def run_all_tasks():
    """Run every deep-work task in sequence. Each is independent — failure of one doesn't stop others."""
    start = datetime.utcnow()
    print(f"[WORKER] ===== DAILY DEEP-WORK RUN STARTED {start.isoformat()} =====")

    # ── Core initialisation ──────────────────────────────────────────────────
    # Each module's init_tables is idempotent — safe to call
    try:
        from app.core.learning import init_learning_tables
        from app.core.episodic_memory import init_episodic_tables
        from app.core.world_model import init_world_model
        from app.core.proactive import init_proactive_tables
        init_learning_tables()
        init_episodic_tables()
        init_world_model()
        init_proactive_tables()
    except Exception as e:
        print(f"[WORKER] Table init issue: {e}")

    # ── Tasks, in order of dependency and priority ───────────────────────────

    # 1. Weekly learning synthesis — rewrites Tony's behaviour rules from 7 days
    try:
        from app.core.learning import run_weekly_learning_synthesis
        await _safe_run("weekly_learning_synthesis", run_weekly_learning_synthesis)
    except ImportError as e:
        _log_task("weekly_learning_synthesis", False, 0, f"Import failed: {e}")

    # 2. Memory consolidation — merges duplicates, builds composite patterns
    try:
        from app.core.memory_consolidator import run_memory_consolidation
        await _safe_run("memory_consolidation", run_memory_consolidation)
    except ImportError as e:
        _log_task("memory_consolidation", False, 0, f"Import failed: {e}")

    # 3. Deep pattern analysis — 7-day rhythm detection
    try:
        from app.core.pattern_recognition import run_pattern_analysis
        await _safe_run("pattern_analysis", run_pattern_analysis)
    except ImportError as e:
        _log_task("pattern_analysis", False, 0, f"Import failed: {e}")

    # 4. Strategic weekly assessment — Tony's life trajectory review
    try:
        from app.core.strategic_advisor import run_strategic_advisor
        await _safe_run("strategic_advisor", run_strategic_advisor)
    except ImportError as e:
        _log_task("strategic_advisor", False, 0, f"Import failed: {e}")

    # 5. Meta-cognition — Tony thinks about his own thinking, detects drift
    try:
        from app.core.meta_cognition import run_meta_cognition
        await _safe_run("meta_cognition", run_meta_cognition)
    except ImportError as e:
        _log_task("meta_cognition", False, 0, f"Import failed: {e}")

    # 6. Self-improvement — analyses failures, rewrites behaviour rules
    try:
        from app.core.self_improvement import run_self_improvement
        await _safe_run("self_improvement", run_self_improvement)
    except ImportError as e:
        _log_task("self_improvement", False, 0, f"Import failed: {e}")

    # 7. Self-repair cycle — audit systems, flag real issues
    try:
        from app.core.self_repair import run_self_repair_cycle
        await _safe_run("self_repair_cycle", run_self_repair_cycle)
    except ImportError as e:
        _log_task("self_repair_cycle", False, 0, f"Import failed: {e}")

    # 8. Code intelligence — review and improve own functions
    try:
        from app.core.code_intelligence import run_code_intelligence_cycle
        await _safe_run("code_intelligence_cycle", run_code_intelligence_cycle)
    except ImportError as e:
        _log_task("code_intelligence_cycle", False, 0, f"Import failed: {e}")

    # 9. Financial intelligence — full scan of email history
    try:
        from app.core.financial_intelligence import run_financial_intelligence
        await _safe_run("financial_intelligence", run_financial_intelligence)
    except ImportError as e:
        _log_task("financial_intelligence", False, 0, f"Import failed: {e}")

    # 10. Relationship intelligence — family dates, milestones
    try:
        from app.core.relationship_intelligence import run_relationship_intelligence
        await _safe_run("relationship_intelligence", run_relationship_intelligence)
    except ImportError as e:
        _log_task("relationship_intelligence", False, 0, f"Import failed: {e}")

    # 11. Income intelligence — deeper research on resale opportunities
    try:
        from app.core.income_engine import run_income_intelligence
        await _safe_run("income_intelligence", run_income_intelligence)
    except ImportError as e:
        _log_task("income_intelligence", False, 0, f"Import failed: {e}")

    # 12. Marketplace intelligence — arbitrage opportunities
    try:
        from app.core.marketplace_monitor import run_marketplace_intelligence
        await _safe_run("marketplace_intelligence", run_marketplace_intelligence)
    except ImportError as e:
        _log_task("marketplace_intelligence", False, 0, f"Import failed: {e}")

    # 13. Anticipation engine — predicts needs before asked
    try:
        from app.core.anticipation_engine import run_anticipation_engine
        await _safe_run("anticipation_engine", run_anticipation_engine)
    except ImportError as e:
        _log_task("anticipation_engine", False, 0, f"Import failed: {e}")

    # 14. Daily journal reflection — Tony's private thoughts
    try:
        from app.core.tony_journal import write_daily_reflection
        await _safe_run("daily_reflection", write_daily_reflection)
    except ImportError as e:
        _log_task("daily_reflection", False, 0, f"Import failed: {e}")

    # ── Summary ──────────────────────────────────────────────────────────────
    duration = (datetime.utcnow() - start).total_seconds()
    print(f"[WORKER] ===== RUN COMPLETE in {duration:.1f}s =====")

    # Write a summary alert so Matthew can see it in the morning briefing
    try:
        from app.core.proactive import create_alert
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), SUM(CASE WHEN success THEN 1 ELSE 0 END)
            FROM tony_worker_log
            WHERE ran_at > NOW() - INTERVAL '2 hours'
        """)
        row = cur.fetchone()
        total = row[0] if row else 0
        ok = row[1] if row else 0
        cur.close()
        conn.close()

        if total > 0:
            create_alert(
                alert_type="worker_summary",
                title=f"Overnight work complete: {ok}/{total} tasks",
                body=f"Tony's daily deep work ran overnight. {ok} of {total} tasks completed successfully in {duration:.0f}s.",
                priority="low",
                source="think_worker",
                expires_hours=18,
                dedup_hours=20
            )
    except Exception as e:
        print(f"[WORKER] Summary alert failed: {e}")


if __name__ == "__main__":
    asyncio.run(run_all_tasks())
