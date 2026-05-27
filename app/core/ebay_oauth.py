"""eBay OAuth — User Token Authorization Code Grant flow for sandbox + prod.

Design contract: nova-docs/ops/evidence/2026-05-25/SESSION_BRIEF_ebay_oauth_design.md

Key shape:
- Single callback endpoint at /api/v1/ebay/oauth/callback; environment carried
  inside OAuth `state` as f"{env}:{nonce}". The state nonce alone is stored in
  tony_ebay_oauth_states (env lives in the row's environment column).
- access_token + refresh_token Fernet-encrypted at rest using TOKEN_ENCRYPTION_KEY
  Railway Variable on the web service. Key rotation requires re-consent (we do
  not maintain a re-encrypt-with-new-key migration for this single-user setup).
- Per-call psycopg2 connections (sslmode='require'), matching gmail_service.py
  and app/selling/jobs.py convention.
- Every failure path catches Exception, calls record_run_event(
  subsystem='selling.ebay.oauth', ...), returns None / False. Never raises.

Public surface used by app/api/v1/endpoints/ebay.py:
  init_ebay_oauth_tables, get_auth_url, consume_state, exchange_code,
  fetch_ebay_user_id, save_tokens, refresh_access_token, get_token_status.
"""

import os
import base64
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import httpx
import psycopg2
from cryptography.fernet import Fernet, InvalidToken

from app.observability import record_run_event, EventSeverity, EVENT_TYPES


# ── Environment-keyed config ─────────────────────────────────────────────────
# Credentials live in Railway Variables on the web service. RuNames are public
# OAuth identifiers and safe to log fully; client IDs and secrets are NOT.
# Lambdas defer env reads so the module imports cleanly even if vars are unset
# at startup (e.g. in the HANDOVER.md import test).
_CONFIG = {
    "sandbox": {
        "client_id":     lambda: os.environ.get("EBAY_SANDBOX_CLIENT_ID", ""),
        "client_secret": lambda: os.environ.get("EBAY_SANDBOX_CLIENT_SECRET", ""),
        "ru_name":       lambda: os.environ.get("EBAY_SANDBOX_REDIRECT_URI", ""),
        "authorize_url": "https://auth.sandbox.ebay.com/oauth2/authorize",
        "token_url":     "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
        "identity_host": "https://apiz.sandbox.ebay.com",
    },
    "prod": {
        "client_id":     lambda: os.environ.get("EBAY_PROD_CLIENT_ID", ""),
        "client_secret": lambda: os.environ.get("EBAY_PROD_CLIENT_SECRET", ""),
        "ru_name":       lambda: os.environ.get("EBAY_PROD_REDIRECT_URI", ""),
        "authorize_url": "https://auth.ebay.com/oauth2/authorize",
        "token_url":     "https://api.ebay.com/identity/v1/oauth2/token",
        "identity_host": "https://apiz.ebay.com",
    },
}

_VALID_ENVS = frozenset(_CONFIG.keys())

# commerce.identity.readonly is here to populate ebay_user_id on the token row
# at consent time. If we never end up consuming ebay_user_id downstream, this
# scope can be dropped — but each scope removal triggers re-consent, so leave
# it unless storage hygiene becomes a problem.
_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
]


def _get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


def _fernet() -> Fernet:
    """Build a Fernet cipher from TOKEN_ENCRYPTION_KEY each call. Cheap; lazy so
    module import doesn't fail when the var is unset (import-test scenario)."""
    key = os.environ.get("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError("TOKEN_ENCRYPTION_KEY not set in environment")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def _decrypt(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode()


# ── Schema init (called from app/api/v1/router.py _inits list) ────────────────
def init_ebay_oauth_tables() -> None:
    """Create tony_ebay_tokens + tony_ebay_oauth_states if not present. Idempotent."""
    try:
        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tony_ebay_tokens (
                        id BIGSERIAL PRIMARY KEY,
                        environment TEXT NOT NULL CHECK (environment IN ('sandbox','prod')),
                        ebay_user_id TEXT NULL,
                        access_token TEXT NOT NULL,
                        refresh_token TEXT NOT NULL,
                        access_token_expires_at TIMESTAMPTZ NOT NULL,
                        refresh_token_expires_at TIMESTAMPTZ NOT NULL,
                        scopes TEXT[] NOT NULL DEFAULT '{}',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (environment)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tony_ebay_oauth_states (
                        state_token TEXT PRIMARY KEY,
                        environment TEXT NOT NULL CHECK (environment IN ('sandbox','prod')),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ebay_oauth_states_created_at
                        ON tony_ebay_oauth_states (created_at)
                """)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[EBAY_OAUTH] init_ebay_oauth_tables failed: {e}")


# ── OAuth URL builder + state consume ────────────────────────────────────────
def get_auth_url(env: str) -> Optional[str]:
    """Generate nonce, insert state row, TTL-sweep stale rows, build authorize URL.

    Returns None on invalid env, missing creds, or DB write failure.
    """
    try:
        if env not in _VALID_ENVS:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.ebay.oauth",
                message=f"get_auth_url called with invalid env={env!r}",
                metadata={"env": env},
            )
            return None

        cfg = _CONFIG[env]
        client_id = cfg["client_id"]()
        ru_name = cfg["ru_name"]()
        if not client_id or not ru_name:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message=f"missing EBAY_{env.upper()}_CLIENT_ID or EBAY_{env.upper()}_REDIRECT_URI",
                metadata={
                    "env": env,
                    "has_client_id": bool(client_id),
                    "has_ru_name": bool(ru_name),
                },
            )
            return None

        nonce = secrets.token_urlsafe(32)

        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tony_ebay_oauth_states (state_token, environment) VALUES (%s, %s)",
                    (nonce, env),
                )
                cur.execute(
                    "DELETE FROM tony_ebay_oauth_states WHERE created_at < NOW() - INTERVAL '10 minutes'"
                )
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # redirect_uri value is the RuName, not a real URL — eBay's Dev Portal
        # maps the RuName to the actual callback URL we expose at
        # /api/v1/ebay/oauth/callback. Don't confuse this with stdlib OAuth.
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": ru_name,
            "scope": " ".join(_SCOPES),
            "state": f"{env}:{nonce}",
        }
        return f"{cfg['authorize_url']}?{urllib.parse.urlencode(params)}"
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.ebay.oauth",
            message="get_auth_url failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"env": env},
        )
        return None


def consume_state(state: str) -> Optional[str]:
    """Parse 'env:nonce' state, DELETE matching row, return env on success.

    Returns None for malformed state, unknown nonce, expired (TTL-swept) row, or
    env-in-state-doesn't-match-env-in-row. Single split on ':' so a nonce that
    somehow contained ':' would still parse safely (token_urlsafe never emits ':').
    """
    try:
        if not state or ":" not in state:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.ebay.oauth",
                message="consume_state: malformed state (no colon)",
                metadata={"state_len": len(state) if state else 0},
            )
            return None

        env, nonce = state.split(":", 1)
        if env not in _VALID_ENVS:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.ebay.oauth",
                message=f"consume_state: invalid env prefix={env!r}",
                metadata={"env": env},
            )
            return None

        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                # created_at predicate enforces the 10-min TTL atomically at
                # consume time. Without it, an expired row stays usable until
                # the next get_auth_url() sweeps it (codex review session 4,
                # finding 2). Belt-and-braces against the init-time sweep.
                cur.execute(
                    """
                    DELETE FROM tony_ebay_oauth_states
                    WHERE state_token = %s AND environment = %s
                      AND created_at > NOW() - INTERVAL '10 minutes'
                    RETURNING 1
                    """,
                    (nonce, env),
                )
                row = cur.fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not row:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.ebay.oauth",
                message="consume_state: nonce unknown, expired, or env mismatch — callback rejected",
                metadata={"env": env},
            )
            return None
        return env
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.ebay.oauth",
            message="consume_state failed",
            error_class=type(e).__name__,
            error_message=str(e),
        )
        return None


# ── Token exchange + refresh ──────────────────────────────────────────────────
async def exchange_code(env: str, code: str) -> Optional[Dict[str, Any]]:
    """POST authorization code → eBay token endpoint. Returns dict with
    {access_token, refresh_token, expires_in, refresh_token_expires_in, scope}
    on success, None on any failure."""
    try:
        if env not in _VALID_ENVS:
            return None

        cfg = _CONFIG[env]
        client_id = cfg["client_id"]()
        client_secret = cfg["client_secret"]()
        ru_name = cfg["ru_name"]()
        if not (client_id and client_secret and ru_name):
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message="exchange_code: missing eBay creds in env",
                metadata={"env": env},
            )
            return None

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    cfg["token_url"],
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": ru_name,
                    },
                )
        except httpx.TimeoutException as e:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_TIMEOUT"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message="exchange_code: token endpoint timeout",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"env": env},
            )
            return None

        if resp.status_code != 200:
            # Don't echo response body — error responses can include reflected
            # client_id and we don't log credential-shaped values.
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_ERROR"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message=f"exchange_code: token endpoint returned {resp.status_code}",
                metadata={"env": env, "status": resp.status_code},
            )
            return None

        return resp.json()
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["PROVIDER_ERROR"],
            severity=EventSeverity.ERROR,
            subsystem="selling.ebay.oauth",
            message="exchange_code failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"env": env},
        )
        return None


async def refresh_access_token(env: str) -> Optional[str]:
    """Pull-based refresh. Returns existing access token if >5 min from expiry;
    otherwise POSTs grant_type=refresh_token, updates row, returns new token.

    Returns None on any failure (no row, missing creds, HTTP error, DB error,
    Fernet decrypt failure).
    """
    try:
        if env not in _VALID_ENVS:
            return None

        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT access_token, refresh_token, access_token_expires_at
                    FROM tony_ebay_tokens WHERE environment = %s
                    """,
                    (env,),
                )
                row = cur.fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not row:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.WARNING,
                subsystem="selling.ebay.oauth",
                message=f"refresh_access_token: no row for env={env}",
                metadata={"env": env},
            )
            return None

        enc_access, enc_refresh, expires_at = row

        # Decrypt — Fernet failure here is critical: stored tokens are
        # unrecoverable, almost certainly because TOKEN_ENCRYPTION_KEY was
        # rotated without re-consent. Flag loudly.
        try:
            access = _decrypt(enc_access)
            refresh = _decrypt(enc_refresh)
        except (InvalidToken, ValueError) as e:
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.CRITICAL,
                subsystem="selling.ebay.oauth",
                message="refresh_access_token: Fernet decrypt failed — stored tokens unrecoverable (TOKEN_ENCRYPTION_KEY rotation without re-consent?)",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"env": env},
            )
            return None

        now = datetime.now(timezone.utc)
        if expires_at and now < expires_at - timedelta(minutes=5):
            return access

        cfg = _CONFIG[env]
        client_id = cfg["client_id"]()
        client_secret = cfg["client_secret"]()
        if not (client_id and client_secret):
            record_run_event(
                event_type=EVENT_TYPES["CAPABILITY_UNAVAILABLE"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message="refresh_access_token: missing eBay creds in env",
                metadata={"env": env},
            )
            return None

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    cfg["token_url"],
                    headers={
                        "Authorization": f"Basic {basic}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                        "scope": " ".join(_SCOPES),
                    },
                )
        except httpx.TimeoutException as e:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_TIMEOUT"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message="refresh_access_token: token endpoint timeout",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"env": env},
            )
            return None

        if resp.status_code != 200:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_ERROR"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message=f"refresh_access_token: token endpoint returned {resp.status_code}",
                metadata={"env": env, "status": resp.status_code},
            )
            return None

        data = resp.json()
        new_access = data.get("access_token")
        new_expires_in = int(data.get("expires_in", 7200))
        if not new_access:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_ERROR"],
                severity=EventSeverity.ERROR,
                subsystem="selling.ebay.oauth",
                message="refresh_access_token: response missing access_token field",
                metadata={"env": env},
            )
            return None

        new_expires_at = now + timedelta(seconds=new_expires_in)
        new_enc_access = _encrypt(new_access)

        # eBay usually leaves refresh tokens unchanged on refresh but can rotate
        # them. If the response carries a new refresh_token + expiry, persist it.
        new_refresh = data.get("refresh_token")
        new_refresh_expires_in = data.get("refresh_token_expires_in")

        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                if new_refresh and new_refresh_expires_in:
                    new_enc_refresh = _encrypt(new_refresh)
                    new_refresh_expires_at = now + timedelta(seconds=int(new_refresh_expires_in))
                    cur.execute(
                        """
                        UPDATE tony_ebay_tokens SET
                            access_token = %s,
                            access_token_expires_at = %s,
                            refresh_token = %s,
                            refresh_token_expires_at = %s,
                            updated_at = NOW()
                        WHERE environment = %s
                        """,
                        (
                            new_enc_access, new_expires_at,
                            new_enc_refresh, new_refresh_expires_at,
                            env,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE tony_ebay_tokens SET
                            access_token = %s,
                            access_token_expires_at = %s,
                            updated_at = NOW()
                        WHERE environment = %s
                        """,
                        (new_enc_access, new_expires_at, env),
                    )
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return new_access
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.ebay.oauth",
            message="refresh_access_token failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"env": env},
        )
        return None


# ── Persistence ───────────────────────────────────────────────────────────────
def save_tokens(
    env: str,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    refresh_token_expires_in: int,
    scopes: List[str],
    ebay_user_id: Optional[str] = None,
) -> bool:
    """Encrypt tokens, INSERT … ON CONFLICT (environment) DO UPDATE. Returns
    True on success, False on any failure."""
    try:
        if env not in _VALID_ENVS:
            return False

        enc_access = _encrypt(access_token)
        enc_refresh = _encrypt(refresh_token)
        now = datetime.now(timezone.utc)
        access_expires_at = now + timedelta(seconds=int(expires_in))
        refresh_expires_at = now + timedelta(seconds=int(refresh_token_expires_in))

        conn = _get_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tony_ebay_tokens (
                        environment, ebay_user_id,
                        access_token, refresh_token,
                        access_token_expires_at, refresh_token_expires_at,
                        scopes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (environment) DO UPDATE SET
                        ebay_user_id = EXCLUDED.ebay_user_id,
                        access_token = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        access_token_expires_at = EXCLUDED.access_token_expires_at,
                        refresh_token_expires_at = EXCLUDED.refresh_token_expires_at,
                        scopes = EXCLUDED.scopes,
                        updated_at = NOW()
                    """,
                    (
                        env, ebay_user_id, enc_access, enc_refresh,
                        access_expires_at, refresh_expires_at, list(scopes),
                    ),
                )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return True
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_WRITE_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.ebay.oauth",
            message="save_tokens failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"env": env},
        )
        return False


def get_token_status() -> Dict[str, Any]:
    """Per-env presence + expiry timestamps + ebay_user_id. Never returns raw
    tokens. Returns {} on DB read failure."""
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT environment, ebay_user_id,
                           access_token_expires_at, refresh_token_expires_at,
                           updated_at
                    FROM tony_ebay_tokens
                    """
                )
                rows = cur.fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        out: Dict[str, Any] = {
            "sandbox": {"present": False},
            "prod": {"present": False},
        }
        for env, user_id, access_exp, refresh_exp, updated_at in rows:
            out[env] = {
                "present": True,
                "ebay_user_id": user_id,
                "access_token_expires_at": access_exp.isoformat() if access_exp else None,
                "refresh_token_expires_at": refresh_exp.isoformat() if refresh_exp else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }
        return out
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["MEMORY_READ_FAILED"],
            severity=EventSeverity.ERROR,
            subsystem="selling.ebay.oauth",
            message="get_token_status failed",
            error_class=type(e).__name__,
            error_message=str(e),
        )
        return {}


# ── Identity helper (best-effort ebay_user_id population at consent time) ───
async def fetch_ebay_user_id(env: str, access_token: str) -> Optional[str]:
    """Best-effort call to commerce.identity.readonly to populate ebay_user_id.
    Failure is non-fatal — callback handler stores the row without it and a
    later session can backfill if useful."""
    try:
        if env not in _VALID_ENVS:
            return None
        cfg = _CONFIG[env]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{cfg['identity_host']}/commerce/identity/v1/user/",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.TimeoutException as e:
            record_run_event(
                event_type=EVENT_TYPES["PROVIDER_TIMEOUT"],
                severity=EventSeverity.WARNING,
                subsystem="selling.ebay.oauth",
                message="fetch_ebay_user_id: identity endpoint timeout",
                error_class=type(e).__name__,
                error_message=str(e),
                metadata={"env": env},
            )
            return None
        if resp.status_code != 200:
            return None
        body = resp.json()
        return body.get("userId") or body.get("username")
    except Exception as e:
        record_run_event(
            event_type=EVENT_TYPES["PROVIDER_ERROR"],
            severity=EventSeverity.WARNING,
            subsystem="selling.ebay.oauth",
            message="fetch_ebay_user_id failed",
            error_class=type(e).__name__,
            error_message=str(e),
            metadata={"env": env},
        )
        return None
