"""eBay OAuth endpoints.

Design contract: nova-docs/ops/evidence/2026-05-25/SESSION_BRIEF_ebay_oauth_design.md

Routes:
- GET /api/v1/ebay/auth/{env}/init    (verify_token)  → {auth_url, env}
- GET /api/v1/ebay/oauth/callback     (public)        → exchanges code, saves tokens
- GET /api/v1/ebay/status             (verify_token)  → presence + expiry per env

The callback is a SINGLE endpoint for both envs; environment rides inside the
OAuth `state` parameter as f"{env}:{nonce}". This matches the URL registered in
the eBay Dev Portal against both RuNames; per-env callback paths are not used.

There is intentionally NO public /ebay/connect/{env} 302 wrapper (the design
brief originally called for one matching the gmail pattern). Codex flagged
that public init would let an unauthenticated visitor consent with their own
account, and the callback's INSERT…ON CONFLICT (environment) DO UPDATE would
silently overwrite Nova's token row. Consent must start at the authenticated
/auth/{env}/init route; the operator opens the returned auth_url in a browser.

HTML responses (callback success/error pages) never include token values. All
echoed strings are html.escape()'d as defence in depth — env values are already
validated against {sandbox, prod} by the time they reach the templates.
"""

import html
from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import HTMLResponse

from app.core.security import verify_token
from app.core.ebay_oauth import (
    get_auth_url,
    consume_state,
    exchange_code,
    fetch_ebay_user_id,
    save_tokens,
    get_token_status,
)

router = APIRouter()

_VALID_ENVS = {"sandbox", "prod"}


def _validate_env(env: str) -> str:
    if env not in _VALID_ENVS:
        raise HTTPException(status_code=400, detail="env must be 'sandbox' or 'prod'")
    return env


@router.get("/ebay/auth/{env}/init")
async def ebay_auth_init(env: str = Path(...), _=Depends(verify_token)):
    env = _validate_env(env)
    url = get_auth_url(env)
    if not url:
        raise HTTPException(
            status_code=503,
            detail="eBay OAuth init failed; check server logs (selling.ebay.oauth subsystem)",
        )
    return {"auth_url": url, "env": env}


@router.get("/ebay/oauth/callback")
async def ebay_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None,
):
    """Single callback for both envs. Parses state, exchanges code, saves
    encrypted tokens. Returns HTML page (success or error). Never echoes tokens."""
    if error or not code or not state:
        return HTMLResponse(
            _error_html(
                f"eBay returned an error or omitted code/state: "
                f"{html.escape(error or 'missing code/state')}"
            ),
            status_code=400,
        )

    env = consume_state(state)
    if not env:
        return HTMLResponse(
            _error_html(
                "State token unknown, expired (>10 min), or environment mismatch. "
                "Start the consent flow again from /api/v1/ebay/connect/{env}."
            ),
            status_code=400,
        )

    tokens = await exchange_code(env, code)
    if not tokens:
        return HTMLResponse(
            _error_html("Failed to exchange authorization code for tokens — see server logs."),
            status_code=502,
        )

    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")
    refresh_expires_in = tokens.get("refresh_token_expires_in")
    scope_str = tokens.get("scope", "")
    scopes = scope_str.split(" ") if scope_str else []

    if not (access and refresh and expires_in and refresh_expires_in):
        return HTMLResponse(
            _error_html("Token response from eBay missing required fields."),
            status_code=502,
        )

    # Best-effort identity lookup; failure is non-fatal (saves row without it).
    ebay_user_id = await fetch_ebay_user_id(env, access)

    ok = save_tokens(
        env, access, refresh, expires_in, refresh_expires_in, scopes, ebay_user_id
    )
    if not ok:
        return HTMLResponse(
            _error_html("Tokens received but failed to persist — see server logs."),
            status_code=500,
        )

    return HTMLResponse(_success_html(env, ebay_user_id))


@router.get("/ebay/status")
async def ebay_status(_=Depends(verify_token)):
    """Presence + expiry per env. Never returns raw token values."""
    return get_token_status()


# ── HTML pages — never include token values ──────────────────────────────────
def _success_html(env: str, ebay_user_id: str = None) -> str:
    safe_env = html.escape(env)
    safe_user = html.escape(ebay_user_id) if ebay_user_id else "(user id not retrieved — non-fatal, can backfill)"
    return (
        '<html><body style="font-family:sans-serif;padding:40px;background:#1a1225;color:#fff;">'
        f'<h2>✅ eBay {safe_env} connected to Tony</h2>'
        '<p>Tokens persisted (Fernet-encrypted at rest).</p>'
        f'<p>eBay user id: {safe_user}</p>'
        '<p>You can close this page and return to Nova.</p>'
        '</body></html>'
    )


def _error_html(message: str) -> str:
    safe = html.escape(message)
    return (
        '<html><body style="font-family:sans-serif;padding:40px;background:#1a1225;color:#fff;">'
        '<h2>❌ eBay connection failed</h2>'
        f'<p>{safe}</p>'
        '<p>Check server logs (selling.ebay.oauth subsystem) and try again.</p>'
        '</body></html>'
    )
