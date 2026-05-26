-- Nova selling operator session 4: eBay OAuth persistence
-- (tony_ebay_tokens + tony_ebay_oauth_states)
--
-- Design contract: nova-docs/ops/evidence/2026-05-25/SESSION_BRIEF_ebay_oauth_design.md
--
-- Single-user invariant enforced via UNIQUE (environment) on tony_ebay_tokens
-- — one sandbox row, one prod row, ever. Re-consent uses INSERT … ON CONFLICT
-- (environment) DO UPDATE.
--
-- access_token and refresh_token are TEXT (not BYTEA) because Fernet output is
-- urlsafe-base64. Encryption is applied at the application layer via
-- app/core/ebay_oauth.py _encrypt/_decrypt helpers using TOKEN_ENCRYPTION_KEY
-- from Railway Variables on the web service.
--
-- ebay_user_id is the eBay-side identifier from commerce.identity.readonly —
-- not a Nova-side user discriminator (which would violate the no-user_id rule).
--
-- tony_ebay_oauth_states is the CSRF-state store; rows live ~10 minutes
-- (deleted on consume + TTL-swept on each new init).

CREATE TABLE IF NOT EXISTS tony_ebay_tokens (
    id BIGSERIAL PRIMARY KEY,
    environment TEXT NOT NULL CHECK (environment IN ('sandbox','prod')),
    ebay_user_id TEXT NULL,
    access_token TEXT NOT NULL,                  -- Fernet-encrypted
    refresh_token TEXT NOT NULL,                 -- Fernet-encrypted
    access_token_expires_at TIMESTAMPTZ NOT NULL,
    refresh_token_expires_at TIMESTAMPTZ NOT NULL,
    scopes TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (environment)
);

CREATE TABLE IF NOT EXISTS tony_ebay_oauth_states (
    state_token TEXT PRIMARY KEY,
    environment TEXT NOT NULL CHECK (environment IN ('sandbox','prod')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ebay_oauth_states_created_at
    ON tony_ebay_oauth_states (created_at);
