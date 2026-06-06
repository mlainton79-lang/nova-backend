"""
approval_lock.py — Foundation tables for the governor narrow-fix.

First code-layer brick of the governor narrow-fix. Creates the three tables
and the immutability/state-machine trigger that the (later) approve/deny/list
endpoints and the (later) governor.py:215 replacement will sit on top of.

The PROD source of truth per AGENTS.md:32 is this init function. The matching
SQL file `db/migrations/20260606120000_create_approval_lock_tables.sql` is the
audit-history mirror; the two must stay byte-equivalent in their schema.

Tables created:
  - tony_approval_devices    (alpha §1 — enrolled devices, secret_hash, status)
  - tony_pending_approvals   (alpha §2 — actions awaiting approval)
  - tony_action_grants       (lock-design §3 + alpha §3 — one-time grants)

Trigger created:
  - tony_pending_approvals_guard (BEFORE INSERT OR UPDATE) — enforces
    immutability + state machine + write-once monotonicity + per-status
    companion consistency per alpha §2 + alpha-r2 fixes #1, #2, #6.

Design references:
  - nova-docs/2026-06-05-governor-narrow-fix-design.md          (lock design, 10fbf07)
  - nova-docs/2026-06-06-approval-auth-alpha-design.md          (alpha auth,  f0adcde)
  - nova-docs/2026-06-05-schema-drift-audit.md                  (drift hazard, [KNOWN GAP])

Foundational contract per AGENTS.md:
  - init_approval_lock_tables() is idempotent (CREATE TABLE IF NOT EXISTS +
    CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS + CREATE TRIGGER).
  - Init failure is printed and non-fatal — the function does not raise. A
    failure to init these tables makes the (later) approval endpoints fail
    closed (a destructive action DENIES with no grant available). That is
    the correct fail-closed posture; nothing else in the request path is
    broken.
"""
import os
import psycopg2


def _connect():
    """Single source of connection shape per AGENTS.md."""
    return psycopg2.connect(
        os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10
    )


# The trigger function body is long; pulled out for readability. Mirrors the
# SQL file's §4 trigger definition byte-for-byte.
_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION tony_pending_approvals_guard() RETURNS TRIGGER AS $$
BEGIN
    -- IMMUTABILITY (UPDATE only)
    IF TG_OP = 'UPDATE' THEN
        IF NEW.pending_id IS DISTINCT FROM OLD.pending_id THEN
            RAISE EXCEPTION 'tony_pending_approvals: pending_id is immutable';
        END IF;
        IF NEW.capability_key IS DISTINCT FROM OLD.capability_key THEN
            RAISE EXCEPTION 'tony_pending_approvals: capability_key is immutable';
        END IF;
        IF NEW.action_hash IS DISTINCT FROM OLD.action_hash THEN
            RAISE EXCEPTION 'tony_pending_approvals: action_hash is immutable';
        END IF;
        IF NEW.action_snapshot IS DISTINCT FROM OLD.action_snapshot THEN
            RAISE EXCEPTION 'tony_pending_approvals: action_snapshot is immutable';
        END IF;
        IF NEW.approval_challenge IS DISTINCT FROM OLD.approval_challenge THEN
            RAISE EXCEPTION 'tony_pending_approvals: approval_challenge is immutable';
        END IF;
        IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'tony_pending_approvals: created_at is immutable';
        END IF;
        IF NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
            RAISE EXCEPTION 'tony_pending_approvals: expires_at is immutable';
        END IF;
    END IF;

    -- STATE MACHINE (UPDATE only)
    IF TG_OP = 'UPDATE' AND NEW.status IS DISTINCT FROM OLD.status THEN
        IF NOT (OLD.status = 'awaiting'
                AND NEW.status IN ('approved', 'denied', 'expired')) THEN
            RAISE EXCEPTION 'tony_pending_approvals: invalid status transition % -> %',
                OLD.status, NEW.status;
        END IF;
    END IF;

    -- WRITE-ONCE MONOTONICITY (UPDATE only)
    IF TG_OP = 'UPDATE' THEN
        IF OLD.approved_at IS NOT NULL
           AND NEW.approved_at IS DISTINCT FROM OLD.approved_at THEN
            RAISE EXCEPTION 'tony_pending_approvals: approved_at is write-once';
        END IF;
        IF OLD.denied_at IS NOT NULL
           AND NEW.denied_at IS DISTINCT FROM OLD.denied_at THEN
            RAISE EXCEPTION 'tony_pending_approvals: denied_at is write-once';
        END IF;
        IF OLD.approved_by_device_id IS NOT NULL
           AND NEW.approved_by_device_id IS DISTINCT FROM OLD.approved_by_device_id THEN
            RAISE EXCEPTION 'tony_pending_approvals: approved_by_device_id is write-once';
        END IF;
        IF OLD.denied_by_device_id IS NOT NULL
           AND NEW.denied_by_device_id IS DISTINCT FROM OLD.denied_by_device_id THEN
            RAISE EXCEPTION 'tony_pending_approvals: denied_by_device_id is write-once';
        END IF;
        IF OLD.approval_challenge_used_at IS NOT NULL
           AND NEW.approval_challenge_used_at IS DISTINCT FROM OLD.approval_challenge_used_at THEN
            RAISE EXCEPTION 'tony_pending_approvals: approval_challenge_used_at is write-once';
        END IF;
        IF OLD.grant_id IS NOT NULL
           AND NEW.grant_id IS DISTINCT FROM OLD.grant_id THEN
            RAISE EXCEPTION 'tony_pending_approvals: grant_id is write-once';
        END IF;
    END IF;

    -- COMPANION CONSISTENCY (INSERT AND UPDATE)
    IF NEW.status = 'awaiting' THEN
        IF NEW.approved_at IS NOT NULL
           OR NEW.approved_by_device_id IS NOT NULL
           OR NEW.denied_at IS NOT NULL
           OR NEW.denied_by_device_id IS NOT NULL
           OR NEW.approval_challenge_used_at IS NOT NULL
           OR NEW.grant_id IS NOT NULL THEN
            RAISE EXCEPTION 'tony_pending_approvals: status=awaiting requires all companion fields NULL';
        END IF;
    ELSIF NEW.status = 'approved' THEN
        IF NEW.approved_at IS NULL
           OR NEW.approved_by_device_id IS NULL
           OR NEW.approval_challenge_used_at IS NULL
           OR NEW.grant_id IS NULL THEN
            RAISE EXCEPTION 'tony_pending_approvals: status=approved requires approved_at + approved_by_device_id + approval_challenge_used_at + grant_id all NON-NULL';
        END IF;
        IF NEW.denied_at IS NOT NULL OR NEW.denied_by_device_id IS NOT NULL THEN
            RAISE EXCEPTION 'tony_pending_approvals: status=approved requires denied_at and denied_by_device_id NULL';
        END IF;
    ELSIF NEW.status = 'denied' THEN
        IF NEW.denied_at IS NULL
           OR NEW.denied_by_device_id IS NULL
           OR NEW.approval_challenge_used_at IS NULL THEN
            RAISE EXCEPTION 'tony_pending_approvals: status=denied requires denied_at + denied_by_device_id + approval_challenge_used_at all NON-NULL';
        END IF;
        IF NEW.approved_at IS NOT NULL
           OR NEW.approved_by_device_id IS NOT NULL
           OR NEW.grant_id IS NOT NULL THEN
            RAISE EXCEPTION 'tony_pending_approvals: status=denied requires approved_at, approved_by_device_id, grant_id all NULL';
        END IF;
    ELSIF NEW.status = 'expired' THEN
        IF NEW.approved_at IS NOT NULL
           OR NEW.approved_by_device_id IS NOT NULL
           OR NEW.denied_at IS NOT NULL
           OR NEW.denied_by_device_id IS NOT NULL
           OR NEW.grant_id IS NOT NULL
           OR NEW.approval_challenge_used_at IS NOT NULL THEN
            RAISE EXCEPTION 'tony_pending_approvals: status=expired requires all companion fields NULL (including approval_challenge_used_at, alpha-r2 #6)';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def init_approval_lock_tables() -> None:
    """Idempotent table + trigger init. Registered in app/api/v1/router.py _inits.

    Mirrors db/migrations/20260606120000_create_approval_lock_tables.sql
    byte-for-byte in its schema. The SQL file is the audit history; this
    function is the prod source of truth.

    ALL DDL runs in ONE atomic transaction (autocommit=False + explicit
    commit). The DROP TRIGGER IF EXISTS + CREATE TRIGGER cycle and the
    ALTER TABLE DROP/ADD CONSTRAINT cycle MUST be atomic — under autocommit
    each DDL would commit independently, opening a fail-open window
    where the trigger or FK is absent and concurrent writes bypass the
    invariants. Closes Codex brick-1 review #1.

    Init failure: rolls back the transaction, prints, and records the
    failure into tony_run_ledger via record_run so the failure is in
    the audit log, not just in stdout. Closes Codex brick-1 review #2.
    The (later) approval endpoints fail closed when the gate cannot
    consult a grant store — that is the design's fail-closed posture
    (destructive actions deny when the schema is missing).
    """
    conn = None
    try:
        conn = _connect()
        # All DDL in ONE atomic transaction. Postgres DDL is transactional;
        # DROP+CREATE pairs would otherwise expose a no-trigger / no-FK
        # window under autocommit. Codex brick-1 review #1.
        conn.autocommit = False
        with conn.cursor() as cur:
            # §1  tony_approval_devices
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tony_approval_devices (
                    device_id       UUID PRIMARY KEY,
                    device_name     TEXT NOT NULL,
                    secret_hash     TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'active',
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    revoked_at      TIMESTAMPTZ,
                    last_seen_at    TIMESTAMPTZ,
                    CHECK (status IN ('active', 'revoked')),
                    CHECK (secret_hash ~ '^[0-9a-f]{64}$'),
                    CHECK ((status = 'active'  AND revoked_at IS NULL)
                        OR (status = 'revoked' AND revoked_at IS NOT NULL))
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tony_approval_devices_active
                    ON tony_approval_devices(status)
                    WHERE status = 'active'
                """
            )

            # §2  tony_pending_approvals
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tony_pending_approvals (
                    pending_id                  UUID PRIMARY KEY,
                    capability_key              TEXT NOT NULL,
                    action_hash                 BYTEA NOT NULL,
                    action_snapshot             JSONB NOT NULL,
                    status                      TEXT NOT NULL DEFAULT 'awaiting',
                    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at                  TIMESTAMPTZ NOT NULL,
                    approval_challenge          BYTEA NOT NULL,
                    approval_challenge_used_at  TIMESTAMPTZ,
                    approved_by_device_id       UUID REFERENCES tony_approval_devices(device_id),
                    approved_at                 TIMESTAMPTZ,
                    denied_by_device_id         UUID REFERENCES tony_approval_devices(device_id),
                    denied_at                   TIMESTAMPTZ,
                    grant_id                    UUID,
                    CHECK (status IN ('awaiting', 'approved', 'denied', 'expired')),
                    CHECK (octet_length(action_hash) = 32),
                    CHECK (octet_length(approval_challenge) >= 16),
                    CHECK (expires_at > created_at)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tony_pending_approvals_awaiting
                    ON tony_pending_approvals(expires_at)
                    WHERE status = 'awaiting'
                """
            )

            # §3  tony_action_grants
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tony_action_grants (
                    grant_id            UUID PRIMARY KEY,
                    capability_key      TEXT NOT NULL,
                    action_hash         BYTEA NOT NULL,
                    pending_action_ref  UUID NOT NULL UNIQUE
                                        REFERENCES tony_pending_approvals(pending_id),
                    minted_by           TEXT NOT NULL DEFAULT 'human_approval',
                    minted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at          TIMESTAMPTZ NOT NULL,
                    consumed_at         TIMESTAMPTZ,
                    status              TEXT NOT NULL DEFAULT 'active',
                    CHECK (status IN ('active', 'consumed', 'expired', 'denied')),
                    CHECK (minted_by = 'human_approval'),
                    CHECK (octet_length(action_hash) = 32),
                    CHECK (expires_at > minted_at),
                    CHECK (
                        (status = 'consumed' AND consumed_at IS NOT NULL)
                        OR (status <> 'consumed' AND consumed_at IS NULL)
                    )
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tony_action_grants_active_by_action
                    ON tony_action_grants(capability_key, action_hash)
                    WHERE status = 'active'
                """
            )

            # Forward FK from tony_pending_approvals.grant_id to
            # tony_action_grants.grant_id (deferred to after both tables exist).
            cur.execute(
                """
                ALTER TABLE tony_pending_approvals
                    DROP CONSTRAINT IF EXISTS tony_pending_approvals_grant_fk
                """
            )
            cur.execute(
                """
                ALTER TABLE tony_pending_approvals
                    ADD CONSTRAINT tony_pending_approvals_grant_fk
                    FOREIGN KEY (grant_id) REFERENCES tony_action_grants(grant_id)
                """
            )

            # §4  Trigger function + trigger
            cur.execute(_TRIGGER_FUNCTION_SQL)
            cur.execute(
                """
                DROP TRIGGER IF EXISTS tony_pending_approvals_guard_trigger
                    ON tony_pending_approvals
                """
            )
            cur.execute(
                """
                CREATE TRIGGER tony_pending_approvals_guard_trigger
                    BEFORE INSERT OR UPDATE ON tony_pending_approvals
                    FOR EACH ROW EXECUTE FUNCTION tony_pending_approvals_guard()
                """
            )

        # Commit ONLY after every DDL succeeds. If any cur.execute() raises,
        # the except branch below rolls back — the trigger and FK never
        # exist in a half-applied state.
        conn.commit()
        print("[APPROVAL_LOCK] Tables and trigger initialised")
    except Exception as e:
        # Roll back the atomic transaction so prod is never left in a
        # half-applied state (closes Codex brick-1 review #1).
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"[APPROVAL_LOCK] Init failed: {e}")
        # Codex brick-1 review #2: record the failure in tony_run_ledger
        # so a security-critical schema-init failure is observable in the
        # audit log, not just in stdout. record_run is documented as
        # never-raises; we still wrap defensively because the ledger schema
        # may not yet exist (init ordering).
        try:
            from app.core.run_ledger import record_run
            record_run(
                action_type="approval_lock.init",
                trigger="startup",
                summary="approval-lock schema init failed",
                status="failed",
                result=str(e)[:1000],
            )
        except Exception:
            # If the ledger write itself fails, the print() above is the
            # last line of defense. Do not re-raise — init is best-effort.
            pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
