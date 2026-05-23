-- Nova Nerve-1A commit 1: run_events table
-- Additive parallel table to run_ledger. Holds operational events Tony emits:
-- memory write failures, provider errors, capability state changes, worker health, etc.
-- Tony reads this via /api/v1/status to surface recent critical events.

CREATE TABLE IF NOT EXISTS run_events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NULL,
    source_service TEXT NOT NULL DEFAULT 'web',
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('debug','info','warning','error','critical')),
    subsystem TEXT NOT NULL,
    capability TEXT NULL,
    status TEXT NULL,
    message TEXT NOT NULL,
    error_class TEXT NULL,
    error_message TEXT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_run_events_created_at
    ON run_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_run_events_severity_created_at
    ON run_events (severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_run_events_subsystem_created_at
    ON run_events (subsystem, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id_created_at
    ON run_events (run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_run_events_capability_created_at
    ON run_events (capability, created_at DESC);
