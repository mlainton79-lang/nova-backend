"""Tony's morning self-check — the nervous system.

One push a day answering one question: is anything broken that Matthew
doesn't know about? Born from the July 2026 week where the database was
down for two and a half days, the OpenAI seat had been dead for months,
and the task-queue worker had been crash-looping unread: nothing in Nova
may be silently broken for more than 24 hours again.

Every check is PASSIVE — database reads only. No token refreshes, no
provider calls, no external requests, no writes (same contract as the
diag scope on /gmail/debug). A self-check that spends money or mutates
state while checking would be part of the problem.

Each check is isolated: one failing check reports itself as broken and
never takes the others down. The self-check reporting its own failure
honestly is a feature.
"""
import os
from datetime import datetime, timedelta

import psycopg2


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def _run_query(sql: str, params=None):
    """One isolated read. Returns (rows, error_string)."""
    conn = None
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, params or ())
                return cur.fetchall(), None
            finally:
                cur.close()
        finally:
            conn.close()
            conn = None
    except Exception as e:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return None, f"{type(e).__name__}: {e}"


def check_database() -> dict:
    rows, err = _run_query("SELECT COUNT(*) FROM memories")
    if err:
        return {"ok": False, "detail": err}
    return {"ok": True, "detail": f"{rows[0][0]} memories"}


def check_gmail_accounts() -> dict:
    rows, err = _run_query(
        "SELECT email, token_expiry, "
        "(refresh_token IS NOT NULL AND refresh_token != '') AS has_refresh "
        "FROM gmail_accounts ORDER BY email"
    )
    if err:
        return {"ok": False, "detail": err}
    if not rows:
        return {"ok": False, "detail": "no accounts configured"}
    stale = []
    for email, expiry, has_refresh in rows:
        short = email.split("@")[0]
        if not has_refresh:
            stale.append(f"{short}: no refresh token")
        elif expiry and expiry < datetime.utcnow() - timedelta(hours=24):
            stale.append(f"{short}: token stale since {expiry:%d %b}")
    if stale:
        return {"ok": False, "detail": "; ".join(stale)}
    return {"ok": True, "detail": f"{len(rows)} accounts healthy"}


def check_task_queue() -> dict:
    rows, err = _run_query(
        "SELECT status, COUNT(*) FROM tony_task_queue "
        "WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY status"
    )
    if err:
        return {"ok": False, "detail": err}
    counts = {status: n for status, n in rows}
    failed = counts.get("failed", 0)
    # Queue writes status='done' on success (Codex P2, review 2a939d6);
    # count 'completed' too defensively in case of legacy rows.
    done = counts.get("done", 0) + counts.get("completed", 0)
    pending = (
        counts.get("queued", 0)
        + counts.get("claimed", 0)
        + counts.get("running", 0)
    )
    detail = f"{done} done, {failed} failed, {pending} pending (24h)"
    return {"ok": failed == 0, "detail": detail}


def check_errors_24h() -> dict:
    rows, err = _run_query(
        "SELECT COALESCE(subsystem, source_service, 'unknown'), COUNT(*) "
        "FROM run_events "
        "WHERE severity IN ('error', 'critical') "
        "  AND created_at > NOW() - INTERVAL '24 hours' "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 4"
    )
    if err:
        return {"ok": False, "detail": err}
    if not rows:
        return {"ok": True, "detail": "no errors logged"}
    top = ", ".join(f"{name} ×{n}" for name, n in rows)
    return {"ok": False, "detail": top}


def check_council_config() -> dict:
    try:
        from app.providers.council import _council_members

        members = _council_members()
        try:
            from app.core.model_router_smart import is_provider_skipped

            disabled = [m for m in members if is_provider_skipped(m)]
        except Exception:
            disabled = []
        if disabled:
            return {
                "ok": False,
                "detail": f"{len(members)} seats, disabled: {', '.join(disabled)}",
            }
        return {"ok": True, "detail": f"{len(members)} seats: {', '.join(members)}"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def gather_self_check() -> dict:
    return {
        "database": check_database(),
        "gmail": check_gmail_accounts(),
        "task_queue": check_task_queue(),
        "errors_24h": check_errors_24h(),
        "council": check_council_config(),
        "generated_at": datetime.utcnow().isoformat(),
    }


_LABELS = {
    "database": "DB",
    "gmail": "Gmail",
    "task_queue": "Tasks",
    "errors_24h": "Errors",
    "council": "Council",
}


def format_self_check(status: dict) -> str:
    lines = []
    for key, label in _LABELS.items():
        c = status.get(key) or {"ok": False, "detail": "check missing"}
        mark = "✅" if c.get("ok") else "⚠️"
        lines.append(f"{mark} {label}: {c.get('detail', '')}")
    return "\n".join(lines)


def self_check_headline(status: dict) -> str:
    warnings = sum(
        1 for k in _LABELS if not (status.get(k) or {}).get("ok")
    )
    if warnings == 0:
        return "Nova self-check: all healthy"
    return f"Nova self-check: {warnings} warning{'s' if warnings != 1 else ''}"


async def deliver_self_check(task_id: int, payload: dict) -> dict:
    """Task handler: gather, format, push, and post as an alert."""
    from app.core.task_queue import update_progress

    update_progress(task_id, "Gathering self-check", 20)
    status = gather_self_check()
    body = format_self_check(status)
    title = self_check_headline(status)

    update_progress(task_id, "Delivering", 70)
    pushed = False
    try:
        from app.core.push_notifications import send_push

        pushed = await send_push(title, body, data={"type": "self_check"})
    except Exception as e:
        print(f"[SELF_CHECK] push failed: {type(e).__name__}: {e}")
    try:
        from app.core.proactive import create_alert

        create_alert(
            "self_check",
            title,
            body,
            priority="normal",
            source="self_check",
            dedup_key=f"self_check_{datetime.utcnow():%Y%m%d}",
        )
    except Exception as e:
        print(f"[SELF_CHECK] alert failed: {type(e).__name__}: {e}")
    next_id = None
    try:
        # Perpetuate the chain: queue tomorrow's run regardless of how
        # delivery went — a failed push must not also kill the heartbeat.
        next_id = schedule_todays_self_check(require_future=True)
    except Exception as e:
        print(f"[SELF_CHECK] chain scheduling failed: {type(e).__name__}: {e}")
    return {"pushed": pushed, "title": title, "next_task_id": next_id}


def register_self_check_handler():
    from app.core.task_queue import register_handler

    register_handler("self_check", deliver_self_check)


def schedule_todays_self_check(hour: int = 7, minute: int = 30,
                               require_future: bool = False):
    """Queue the next self-check at hour:minute if not already covered.

    THE CHAIN (added 23 Jul 2026): startup scheduling alone proved
    deploy-dependent — task #168 ran Wed 07:30 only because Monday's
    deploys spawned it; Tuesday and Thursday had no task at all because
    nobody deployed. The delivery handler therefore calls this with
    require_future=True to queue tomorrow's run at the end of every run:
    a self-perpetuating heartbeat. Startup scheduling remains as the
    bootstrap and the backstop after queue wipes.

    Dedupe (Codex P2, 2a939d6): skip if a pending self_check already
    covers the window. Boundary differs by caller — at startup, any
    pending run newer than an hour ago counts (imminent or future); from
    the handler, only a strictly FUTURE run counts, because the handler's
    own still-running task would otherwise match and skip the chain.
    """
    try:
        boundary = datetime.now() + (
            timedelta(hours=1) if require_future else timedelta(hours=-1)
        )
        rows, err = _run_query(
            "SELECT COUNT(*) FROM tony_task_queue "
            "WHERE task_type = 'self_check' "
            "  AND status IN ('queued', 'claimed', 'running') "
            "  AND scheduled_for > %s",
            (boundary,),
        )
        if err is None and rows and rows[0][0] > 0:
            return None
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        delay = int((target - now).total_seconds())
        from app.core.task_queue import queue_task

        tid = queue_task("self_check", {"scheduled": True}, delay_seconds=delay)
        print(f"[SELF_CHECK] queued task {tid} for {target:%d %b %H:%M}")
        return tid
    except Exception as e:
        print(f"[SELF_CHECK] scheduling failed: {type(e).__name__}: {e}")
        return None
