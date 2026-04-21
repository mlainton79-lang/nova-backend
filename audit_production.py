"""
Production truth audit for Nova backend.

Hits every listed endpoint on the deployed Railway app with a realistic
payload, records status / latency / structural soundness, and prints a
summary table plus error details for anything broken.

Run:  python audit_production.py
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

BASE_URL = "https://web-production-be42b.up.railway.app"
TOKEN = "nova-dev-token"
TIMEOUT_SECS = 60

CHAT_PAYLOAD = {
    "provider": "gemini",
    "message": "Say the single word 'pong' and nothing else.",
    "history": [],
}

COUNCIL_PAYLOAD = {
    "message": "Say the single word 'pong' and nothing else.",
    "history": [],
    "debug": True,
}


@dataclass
class Endpoint:
    method: str
    path: str
    payload: Optional[dict] = None
    stream: bool = False
    notes: str = ""


ENDPOINTS: list[Endpoint] = [
    Endpoint("POST", "/api/v1/chat", CHAT_PAYLOAD),
    Endpoint("POST", "/api/v1/council", COUNCIL_PAYLOAD),
    Endpoint("POST", "/api/v1/chat/stream", CHAT_PAYLOAD, stream=True),
    Endpoint("GET",  "/api/v1/proactive/briefing"),
    Endpoint("GET",  "/api/v1/review/today"),
    Endpoint("GET",  "/api/v1/diary"),
    Endpoint("GET",  "/api/v1/self-goals"),
    Endpoint("GET",  "/api/v1/budget"),
    Endpoint("GET",  "/api/v1/outcomes/satisfaction"),
    Endpoint("POST", "/api/v1/retrieval/search", {"query": "test", "limit": 3}),
    Endpoint("GET",  "/api/v1/facts"),
    Endpoint("GET",  "/api/v1/skills"),
    Endpoint("GET",  "/api/v1/documents"),
    Endpoint("POST", "/api/v1/agentic/run", {"goal": "echo hello", "dry_run": True}),
    Endpoint("GET",  "/api/v1/expenses"),
    Endpoint("GET",  "/api/v1/email-agent/pending"),
    Endpoint("POST", "/api/v1/codebase/sync", {"files": [{"path": "audit.txt", "content": "audit"}]}),
    Endpoint("GET",  "/api/v1/health/dashboard"),
    Endpoint("GET",  "/api/v1/repo/recent"),
]


@dataclass
class Result:
    endpoint: Endpoint
    status: Optional[int]
    latency_ms: int
    ok: bool
    verdict: str
    body_preview: str = ""
    error: str = ""
    parsed: Any = field(default=None)


def _headers(accept: str = "application/json") -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": accept,
    }


def _call(ep: Endpoint) -> Result:
    url = BASE_URL + ep.path
    body = None
    if ep.method == "POST":
        body = json.dumps(ep.payload or {}).encode("utf-8")
    accept = "text/event-stream" if ep.stream else "application/json"
    req = urllib.request.Request(url, data=body, method=ep.method, headers=_headers(accept))

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
            status = resp.status
            if ep.stream:
                raw = _read_sse(resp)
            else:
                raw = resp.read().decode("utf-8", errors="replace")
            latency = int((time.time() - start) * 1000)
            return _judge(ep, status, raw, latency)
    except urllib.error.HTTPError as e:
        latency = int((time.time() - start) * 1000)
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return _judge(ep, e.code, err_body, latency)
    except urllib.error.URLError as e:
        latency = int((time.time() - start) * 1000)
        return Result(ep, None, latency, False, "network error", error=str(e.reason))
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return Result(ep, None, latency, False, "exception", error=f"{type(e).__name__}: {e}")


def _read_sse(resp, max_chunks: int = 20) -> str:
    """Read SSE stream until 'done' event or max_chunks events."""
    events: list[str] = []
    chunks = 0
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        events.append(data)
        chunks += 1
        try:
            j = json.loads(data)
            if j.get("type") in ("done", "error"):
                break
        except Exception:
            pass
        if chunks >= max_chunks:
            break
    return "\n".join(events)


def _judge(ep: Endpoint, status: int, raw: str, latency: int) -> Result:
    body_preview = raw[:400]
    parsed: Any = None
    try:
        parsed = json.loads(raw) if raw and not ep.stream else None
    except Exception:
        parsed = None

    if status >= 500:
        return Result(ep, status, latency, False, f"server error {status}", body_preview, error=raw[:500])
    if status == 404:
        return Result(ep, status, latency, False, "not found", body_preview, error=raw[:500])
    if status in (401, 403):
        return Result(ep, status, latency, False, "auth rejected", body_preview, error=raw[:500])
    if status == 405:
        return Result(ep, status, latency, False, "method not allowed", body_preview, error=raw[:500])
    if status >= 400:
        return Result(ep, status, latency, False, f"client error {status}", body_preview, error=raw[:500])

    # 2xx — structural check
    if ep.stream:
        if not raw.strip():
            return Result(ep, status, latency, False, "empty stream", body_preview)
        if '"type": "error"' in raw or '"type":"error"' in raw:
            return Result(ep, status, latency, False, "stream error event", body_preview, error=raw[:500])
        if '"type": "chunk"' in raw or '"type":"chunk"' in raw or '"type": "done"' in raw or '"type":"done"' in raw:
            return Result(ep, status, latency, True, "stream ok", body_preview, parsed=raw)
        return Result(ep, status, latency, False, "no chunks/done", body_preview, error=raw[:500])

    if not raw.strip():
        return Result(ep, status, latency, False, "empty body", body_preview)

    if isinstance(parsed, dict):
        if parsed.get("ok") is False:
            return Result(ep, status, latency, False, "ok=false in body", body_preview,
                          error=str(parsed.get("error") or parsed)[:500], parsed=parsed)
        if "detail" in parsed and status >= 400:
            return Result(ep, status, latency, False, "FastAPI detail error", body_preview,
                          error=str(parsed.get("detail"))[:500], parsed=parsed)
        return Result(ep, status, latency, True, "ok", body_preview, parsed=parsed)

    if isinstance(parsed, list):
        return Result(ep, status, latency, True, f"ok (list, n={len(parsed)})", body_preview, parsed=parsed)

    if parsed is None:
        # Non-JSON 2xx response
        return Result(ep, status, latency, True, "ok (non-json)", body_preview)

    return Result(ep, status, latency, True, "ok", body_preview, parsed=parsed)


def main() -> None:
    print(f"Auditing {BASE_URL} with token '{TOKEN}'\n")
    results: list[Result] = []
    for ep in ENDPOINTS:
        print(f"  -> {ep.method:4} {ep.path} ...", flush=True)
        results.append(_call(ep))

    # Summary table
    print("\n" + "=" * 88)
    print(f"{'ENDPOINT':<40} {'METHOD':<6} {'STATUS':<7} {'LATENCY':<10} {'VERDICT'}")
    print("=" * 88)
    for r in results:
        status = str(r.status) if r.status is not None else "--"
        verdict = ("OK    " if r.ok else "BROKEN") + "  " + r.verdict
        print(f"{r.endpoint.path:<40} {r.endpoint.method:<6} {status:<7} {r.latency_ms:>5} ms   {verdict}")
    print("=" * 88)

    # Tallies
    ok_count = sum(1 for r in results if r.ok)
    broken_count = len(results) - ok_count
    print(f"\n{ok_count} OK   |   {broken_count} broken   |   {len(results)} total\n")

    # Broken detail
    broken = [r for r in results if not r.ok]
    if broken:
        print("=" * 88)
        print("BROKEN DETAIL")
        print("=" * 88)
        for r in broken:
            print(f"\n{r.endpoint.method} {r.endpoint.path}")
            print(f"  status:  {r.status}")
            print(f"  verdict: {r.verdict}")
            if r.error:
                print(f"  error:   {r.error[:400]}")
            if r.body_preview and r.body_preview != r.error:
                print(f"  body:    {r.body_preview[:400]}")


if __name__ == "__main__":
    main()
