"""
Canonical Gemini API client for Nova backend.

All non-streaming, non-embedding Gemini calls should use this client.
Provides primary-with-fallback for the pro tier so we can ride preview
models while keeping a stable fallback for deprecation events.

Fallback policy (pro tier only):
  - Primary:  GEMINI_PRO_PRIMARY  (default: gemini-3.1-pro-preview)
  - Fallback: GEMINI_PRO_FALLBACK (default: gemini-2.5-pro)

  Triggered on HTTP 404, 410, or 400 with "model not found" /
  "unsupported model" in the error message — Google's signals for
  deprecated / retired models.

  NOT triggered on 503, 429, 502, 504, timeouts, connection errors
  (these are transient and retried once on the same model before
  escalating).

  NOT triggered on 401, 403, other 400s (fatal — bad key, bad request
  shape, safety block — raise immediately).

Fallback cache: 1-hour TTL per pod. Once a deprecation signal hits the
primary, this pod skips the primary for the next hour. Prevents the
wasted round-trip every request after permanent deprecation.

Flash tier is a passthrough to GEMINI_FLASH_MODEL (default:
gemini-2.5-flash). No fallback — there's no flash-preview worth
chasing.

Auth: API key is sent via the `x-goog-api-key` header (not a query
param). This keeps the key out of request URLs, which httpx and other
transport layers may echo into tracebacks and error logs.
"""
import os
import time
import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

PRO_PRIMARY  = os.environ.get("GEMINI_PRO_PRIMARY",  "gemini-3.1-pro-preview")
PRO_FALLBACK = os.environ.get("GEMINI_PRO_FALLBACK", "gemini-2.5-pro")
FLASH_MODEL  = os.environ.get("GEMINI_FLASH_MODEL",  "gemini-2.5-flash")

_FALLBACK_TTL_SECONDS = 3600

# Process-local fallback cache. Mutated from async contexts — safe under
# single-worker CPython (GIL ensures single-assignment atomicity). For
# multi-worker deployments (e.g. gunicorn with workers > 1), this would
# need external state (Redis, memcached) to share deprecation decisions.
# Current Nova runs single-worker on Railway, so this is fine.
_fallback_until: float = 0.0

_ENDPOINT_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_TRANSIENT_STATUSES = {429, 502, 503, 504}
_DEPRECATION_STATUSES = {404, 410}
_DEPRECATION_MESSAGE_MARKERS = ("model not found", "unsupported model")


class GeminiClientError(Exception):
    """Raised on fatal errors or when both pro-tier models exhaust."""


def _looks_like_deprecation_400(status: int, body_text: str) -> bool:
    if status != 400:
        return False
    lower = (body_text or "").lower()
    return any(marker in lower for marker in _DEPRECATION_MESSAGE_MARKERS)


def _should_fallback(status: int, body_text: str) -> bool:
    return status in _DEPRECATION_STATUSES or _looks_like_deprecation_400(status, body_text)


def _should_retry_transient(status: int) -> bool:
    return status in _TRANSIENT_STATUSES


def _cache_mark_fallback() -> None:
    global _fallback_until
    _fallback_until = time.time() + _FALLBACK_TTL_SECONDS


def _cache_says_fallback() -> bool:
    return time.time() < _fallback_until


def _build_body(
    contents: List[Dict[str, Any]],
    system_instruction: Optional[str],
    tools: Optional[List[Dict[str, Any]]],
    generation_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        body["tools"] = tools
    if generation_config:
        body["generationConfig"] = generation_config
    return body


async def _call_once(model: str, body: Dict[str, Any], timeout: float) -> httpx.Response:
    url = _ENDPOINT_TEMPLATE.format(model=model)
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(url, json=body, headers=headers)


async def _call_with_transient_retry(
    model: str,
    body: Dict[str, Any],
    timeout: float,
    caller: str,
) -> httpx.Response:
    """One retry on transient statuses and transport errors, then escalate."""
    for attempt in (1, 2):
        try:
            r = await _call_once(model, body, timeout)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if attempt == 1:
                log.warning(
                    "[GEMINI_CLIENT] %s: %s on %s, retrying once",
                    caller, type(e).__name__, model,
                )
                continue
            raise
        if _should_retry_transient(r.status_code) and attempt == 1:
            log.warning(
                "[GEMINI_CLIENT] %s: HTTP %d on %s, retrying once",
                caller, r.status_code, model,
            )
            continue
        return r
    raise GeminiClientError("transient retry loop exhausted")  # unreachable


async def generate_content(
    tier: str,
    contents: List[Dict[str, Any]],
    system_instruction: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    generation_config: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
    caller_context: str = "",
) -> Dict[str, Any]:
    """Call Gemini generateContent and return the full response JSON.

    tier="pro":   try primary, fall back to stable on deprecation signals.
    tier="flash": passthrough to the configured flash model.

    Raises GeminiClientError on fatal errors (bad key, malformed request,
    safety block) or when both pro-tier models are exhausted. Transient
    errors are retried once per model before escalating.
    """
    if tier not in ("pro", "flash"):
        raise ValueError(f"tier must be 'pro' or 'flash', got {tier!r}")
    if not GEMINI_API_KEY:
        raise GeminiClientError("GEMINI_API_KEY not configured")

    caller = caller_context or "unknown"
    body = _build_body(contents, system_instruction, tools, generation_config)

    if tier == "flash":
        models = [FLASH_MODEL]
    else:
        if _cache_says_fallback():
            log.info("[GEMINI_CLIENT] %s: fallback cache active, skipping primary", caller)
            models = [PRO_FALLBACK]
        else:
            models = [PRO_PRIMARY, PRO_FALLBACK]

    last_status: Optional[int] = None
    last_body: str = ""

    for idx, model in enumerate(models):
        is_last = idx == len(models) - 1
        try:
            r = await _call_with_transient_retry(model, body, timeout, caller)
        except Exception:
            # Safe to log full traceback: API key lives in header, not URL.
            log.exception("[GEMINI_CLIENT] %s: transport error on %s", caller, model)
            if is_last:
                raise GeminiClientError(f"transport failure on {model} (see log)")
            continue

        status = r.status_code
        body_text = r.text if status >= 400 else ""

        if 200 <= status < 300:
            log.info("[GEMINI_CLIENT] %s: success on %s", caller, model)
            return r.json()

        last_status, last_body = status, body_text

        if tier == "pro" and _should_fallback(status, body_text):
            log.warning(
                "[GEMINI_CLIENT] %s: deprecation signal (HTTP %d) on %s, falling back",
                caller, status, model,
            )
            _cache_mark_fallback()
            if is_last:
                break
            continue

        # Fatal: 401, 403, other 400s, or 5xx that survived transient retry.
        msg = f"{model} returned HTTP {status}: {body_text[:500]}"
        log.error("[GEMINI_CLIENT] %s: fatal: %s", caller, msg)
        raise GeminiClientError(msg)

    raise GeminiClientError(
        f"pro-tier exhausted for {caller}: last status={last_status}, body={last_body[:200]}"
    )


def extract_text(response: Dict[str, Any]) -> str:
    """Convenience: pull the first candidate's text from a generateContent response.

    Returns "" if the response has no candidates (safety block) or the
    expected path isn't present. Callers needing finishReason etc. should
    inspect the raw response JSON.
    """
    try:
        return response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""
