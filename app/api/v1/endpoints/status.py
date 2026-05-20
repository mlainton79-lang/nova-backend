"""
Tony Status — single endpoint for the Android Tony Status screen (2am-debugging).
Sibling to /health/dashboard. Gracefully degrades: every sub-check is wrapped so
one slow/broken table can't fail the whole response. Total budget ~8s.
"""
import asyncio
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends

from app.core.security import verify_token
from app.core.gmail_service import get_conn
import httpx

from app.core.run_ledger import recent_runs
from app.core import config

router = APIRouter()

STARTED_AT = time.time()

PER_CHECK_TIMEOUT_S = 5.0
TOTAL_TIMEOUT_S = 8.0
DB_PING_TIMEOUT_S = 1.0


# ─────────── helpers ───────────

def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _trunc(s, n=200):
    s = str(s)
    return s if len(s) <= n else s[:n]


@contextmanager
def _conn():
    c = get_conn()
    try:
        yield c
    finally:
        try:
            c.close()
        except Exception:
            pass


async def _run(fn, timeout=PER_CHECK_TIMEOUT_S):
    """Run a sync fn in a thread with a timeout. Returns the fn's result, or a
    {"status": "timeout"|"error", "error": ...} envelope on failure."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout)
    except asyncio.TimeoutError:
        return {"status": "timeout", "error": f"exceeded {timeout:g}s"}
    except Exception as e:
        return {"status": "error", "error": _trunc(e)}


def _safe_scalar(query, params=None, default=None):
    try:
        with _conn() as c:
            cur = c.cursor()
            try:
                cur.execute(query, params) if params else cur.execute(query)
                row = cur.fetchone()
                return row[0] if row else default
            finally:
                cur.close()
    except Exception:
        return default


# ─────────── B) database ───────────

def _check_db():
    t0 = time.perf_counter()
    with _conn() as c:
        cur = c.cursor()
        try:
            cur.execute("SELECT 1")
            cur.fetchone()
        finally:
            cur.close()
    return {"status": "ok", "latency_ms": round((time.perf_counter() - t0) * 1000)}


# ─────────── E) state.last_memory_write ───────────

def _last_memory_write():
    return {
        "tony_living_memory":   _ts(_safe_scalar("SELECT MAX(updated_at) FROM tony_living_memory")),
        "tony_facts":           _ts(_safe_scalar("SELECT MAX(last_confirmed_at) FROM tony_facts")),
        "tony_episodic_memory": _ts(_safe_scalar("SELECT MAX(created_at) FROM tony_episodic_memory")),
        "semantic_memories":    _ts(_safe_scalar("SELECT MAX(created_at) FROM semantic_memories")),
    }


# ─────────── F) state.last_codebase_sync_* ───────────

def _codebase_sync(source):
    try:
        with _conn() as c:
            cur = c.cursor()
            try:
                cur.execute(
                    "SELECT MAX(updated_at) FROM tony_codebase WHERE source = %s",
                    (source,),
                )
                row = cur.fetchone()
                return _ts(row[0]) if row else None
            finally:
                cur.close()
    except Exception:
        return None


# ─────────── G) state.pending_actions_count ───────────

def _pending_actions_count():
    val = _safe_scalar(
        "SELECT COUNT(*) FROM tony_pending_actions WHERE status = 'pending'",
        default=None,
    )
    return int(val) if val is not None else None


# ─────────── H) state.gmail_accounts ───────────

def _gmail_accounts():
    with _conn() as c:
        cur = c.cursor()
        try:
            cur.execute(
                "SELECT email, token_expiry, updated_at FROM gmail_accounts ORDER BY email"
            )
            rows = cur.fetchall()
        finally:
            cur.close()

    now = datetime.now(timezone.utc)
    soon = now + timedelta(minutes=5)
    out = []
    for email, expiry, _updated in rows:
        if expiry is None:
            status = "expired"
        else:
            exp = expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
            if exp < now:
                status = "expired"
            elif exp < soon:
                status = "expiring_soon"
            else:
                status = "valid"
        out.append({"email": email, "token_expiry": _ts(expiry), "status": status})
    return out


# ─────────── state.recent_activity ───────────

RECENT_ACTIVITY_LIMIT = 10


def _recent_activity():
    """Latest rows from tony_run_ledger - what Tony has actually been doing.

    recent_runs() never raises (returns [] on error) so we don't need extra
    guarding here beyond the standard _run() timeout wrapper.

    Returns a list of dicts with ISO-Z timestamps in place of raw datetimes,
    matching the rest of status.py's serialisation contract.
    """
    rows = recent_runs(limit=RECENT_ACTIVITY_LIMIT)
    out = []
    for r in rows:
        out.append({
            "id": r.get("id"),
            "action_type": r.get("action_type"),
            "trigger": r.get("trigger"),
            "summary": r.get("summary"),
            "status": r.get("status"),
            "result": r.get("result"),
            "trace_id": r.get("trace_id"),
            "created_at": _ts(r.get("created_at")),
            "completed_at": _ts(r.get("completed_at")),
            "metadata": r.get("metadata"),
        })
    return out


# ─────────── infrastructure: github actions workflows ───────────

GITHUB_API_BASE = "https://api.github.com"
GITHUB_REPO = "mlainton79-lang/nova-backend"
WORKFLOW_HTTP_TIMEOUT_S = 4.0


def _workflow_status(workflow_filename: str):
    """Latest run of a named GitHub Actions workflow file.

    Answers: did the cron fire on time? did it succeed? when?
    Used for backup.yml (daily) and restore-drill.yml (weekly + on-demand).

    Returns a dict with name, status, conclusion, started_at, completed_at,
    age_hours, html_url, or an error envelope. Authoritative source for
    backup freshness because GitHub knows when its own cron fired.

    Requires GITHUB_TOKEN env var. Repo is private; unauthenticated calls 404.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
    if not token:
        return {"status": "error", "error": "no GITHUB_TOKEN env"}

    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/workflows/{workflow_filename}/runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"per_page": 1}

    try:
        with httpx.Client(timeout=WORKFLOW_HTTP_TIMEOUT_S) as client:
            r = client.get(url, headers=headers, params=params)
        if r.status_code != 200:
            return {"status": "error", "error": f"http {r.status_code}: {_trunc(r.text, 100)}"}
        data = r.json()
    except Exception as e:
        return {"status": "error", "error": _trunc(e)}

    runs = data.get("workflow_runs") or []
    if not runs:
        return {"status": "ok", "workflow": workflow_filename, "last_run": None}

    run = runs[0]

    # Parse created_at / updated_at for age calculation.
    age_hours = None
    started_iso = run.get("run_started_at") or run.get("created_at")
    completed_iso = run.get("updated_at") if run.get("status") == "completed" else None
    try:
        if started_iso:
            started_dt = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
            age_hours = round((datetime.now(timezone.utc) - started_dt).total_seconds() / 3600.0, 1)
    except Exception:
        pass

    return {
        "status": "ok",
        "workflow": workflow_filename,
        "last_run": {
            "id": run.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "started_at": started_iso,
            "completed_at": completed_iso,
            "age_hours": age_hours,
            "html_url": run.get("html_url"),
            "event": run.get("event"),
        },
    }


def _backup_workflow():
    return _workflow_status("backup.yml")


def _restore_drill_workflow():
    return _workflow_status("restore-drill.yml")


# ─────────── C) providers (env-presence only) ───────────

PROVIDER_KEYS = [
    ("openai",     "OPENAI_API_KEY"),
    ("claude",     "ANTHROPIC_API_KEY"),
    ("gemini",     "GEMINI_API_KEY"),
    ("groq",       "GROQ_API_KEY"),
    ("mistral",    "MISTRAL_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("deepseek",   "DEEPSEEK_API_KEY"),
    ("xai",        "XAI_API_KEY"),
]


def _providers():
    out = []
    for name, env in PROVIDER_KEYS:
        configured = bool(os.environ.get(env))
        out.append({
            "name": name,
            "configured": configured,
            "status": "ok" if configured else "missing_key",
        })
    return out


# ─────────── D) external_services ───────────

def _external_services():
    brave_ok = bool(os.environ.get("BRAVE_API_KEY"))
    return [
        {"name": "brave", "status": "ok" if brave_ok else "missing_key"},
        {"name": "open_meteo", "status": "ok"},
    ]


# ─────────── I,J,K,L) identity ───────────

def _identity():
    return {
        "backend_version": "1.0.0",
        "backend_commit_sha": (
            os.environ.get("GIT_COMMIT_SHA")
            or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
            or "unknown"
        ),
        "backend_deploy_time": (
            os.environ.get("DEPLOY_TIMESTAMP")
            or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            or None
        ),
        "active_feature_flags": {
            "CAPABILITY_BUILDER_STAGING_ENABLED":
                bool(config.CAPABILITY_BUILDER_STAGING_ENABLED),
            "CAPABILITY_BUILDER_AUTONOMOUS_STAGING_ENABLED":
                bool(config.CAPABILITY_BUILDER_AUTONOMOUS_STAGING_ENABLED),
        },
    }


# ─────────── route ───────────

_LAST_MEM_NULL = {
    "tony_living_memory": None,
    "tony_facts": None,
    "tony_episodic_memory": None,
    "semantic_memories": None,
}


def _is_err_envelope(v):
    return isinstance(v, dict) and v.get("status") in ("timeout", "error")


@router.get("/status")
async def tony_status(_=Depends(verify_token)):
    """Tony Status — full snapshot for the Android 2am-debugging screen."""
    backend = {"status": "ok", "uptime_seconds": int(time.time() - STARTED_AT)}

    try:
        db_check, last_mem, sync_fe, sync_be, pending, gmail, activity, backup_wf, drill_wf = await asyncio.wait_for(
            asyncio.gather(
                _run(_check_db, timeout=DB_PING_TIMEOUT_S),
                _run(_last_memory_write),
                _run(lambda: _codebase_sync("frontend")),
                _run(lambda: _codebase_sync("backend")),
                _run(_pending_actions_count),
                _run(_gmail_accounts),
                _run(_recent_activity),
                _run(_backup_workflow),
                _run(_restore_drill_workflow),
            ),
            timeout=TOTAL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        db_check = {"status": "timeout", "error": f"exceeded {TOTAL_TIMEOUT_S:g}s"}
        last_mem = dict(_LAST_MEM_NULL)
        sync_fe = sync_be = None
        pending = None
        gmail = []
        activity = []
        backup_wf = None
        drill_wf = None

    # State fields fall back to spec'd null/empty shapes if a check errored out.
    # (database keeps its own envelope; that's the spec'd shape there.)
    if _is_err_envelope(last_mem):
        last_mem = dict(_LAST_MEM_NULL)
    if _is_err_envelope(sync_fe):
        sync_fe = None
    if _is_err_envelope(sync_be):
        sync_be = None
    if _is_err_envelope(pending):
        pending = None
    if _is_err_envelope(gmail):
        gmail = []
    if _is_err_envelope(activity):
        activity = []

    return {
        "ok": True,
        "generated_at": _now_iso(),
        "health": {
            "backend": backend,
            "database": db_check,
            "providers": _providers(),
            "external_services": _external_services(),
        },
        "state": {
            "last_memory_write": last_mem,
            "last_codebase_sync_frontend": sync_fe,
            "last_codebase_sync_backend": sync_be,
            "pending_actions_count": pending,
            "gmail_accounts": gmail,
            "recent_activity": activity,
        },
        "infrastructure": {
            "backup_workflow": backup_wf,
            "restore_drill_workflow": drill_wf,
        },
        "identity": _identity(),
    }
