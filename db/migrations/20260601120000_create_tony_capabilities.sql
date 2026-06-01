-- R2.1 — Capability Registry v2 (canonicalisation).
--
-- Creates the canonical capability registry table. Supersedes the legacy
-- unprefixed `capabilities` table (predates the tony_ prefix convention).
-- Backfill from legacy is performed at runtime by
-- app.core.capabilities.init_capability_registry_tables() so the existing
-- prompt_assembler / status / gap_detector consumers keep working through
-- the compatibility facade.
--
-- See nova-docs/master_plan_v3_self_extending_agent.md (R2.1 section) and
-- nova-docs/ops/reviews/2026-06-01/codex-review-master-plan-v2.md for the
-- design rationale, including the 22-column forward-compatible shape that
-- accommodates R2.2 planner fields (input_schema / output_schema /
-- invocation_contract / verification_method) as nullable JSONB.

CREATE TABLE IF NOT EXISTS tony_capabilities (
    id                  SERIAL PRIMARY KEY,
    capability_key      TEXT NOT NULL UNIQUE,
    display_name        TEXT,
    description         TEXT NOT NULL,

    status              TEXT NOT NULL DEFAULT 'active',
    capability_type     TEXT NOT NULL,

    locator             TEXT,
    runner              TEXT,
    owner_module        TEXT,

    -- Planner-contract fields. Populated from R2.2 onward; nullable now
    -- to avoid an ALTER TABLE churn when the planner lands.
    input_schema        JSONB,
    output_schema       JSONB,
    invocation_contract JSONB,

    -- Governance fields. Load-bearing from R2.1b governor onward.
    risk_level          TEXT NOT NULL DEFAULT 'low',
    approval_required   BOOLEAN NOT NULL DEFAULT false,
    external_effect     BOOLEAN NOT NULL DEFAULT false,
    cost_type           TEXT NOT NULL DEFAULT 'free',

    verification_method JSONB,
    last_tested_at      TIMESTAMP,
    last_result         TEXT,
    last_error          TEXT,

    source              TEXT,
    tags                TEXT[] DEFAULT '{}',
    notes               TEXT,

    deprecated_at       TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tony_capabilities_status
    ON tony_capabilities(status);

CREATE INDEX IF NOT EXISTS idx_tony_capabilities_type
    ON tony_capabilities(capability_type);

CREATE INDEX IF NOT EXISTS idx_tony_capabilities_tags
    ON tony_capabilities USING GIN(tags);
