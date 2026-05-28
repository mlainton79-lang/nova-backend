-- Nova selling pipeline: tony_drafts (marketplace-agnostic draft store)
--
-- Design contract:
--   nova-docs/ops/evidence/2026-05-28/SESSION_BRIEF_draft_pipeline_design.md
--
-- One row per photo session and one canonical listing candidate, independent
-- of marketplace. User-editable. Source of truth for what should be listed.
-- One draft → N tony_selling_jobs (one per marketplace) — the link from
-- tony_selling_jobs.draft_id back to here lands in a follow-up migration
-- alongside the fan-out endpoint.
--
-- Single-user invariant: there is no user_id column. Per AGENTS.md, the
-- single-user discriminator is the natural one — here it's id itself (each
-- draft is an independent unit of work owned by Matthew).
--
-- Two state machines:
--   status         — draft lifecycle (machine-driven mostly)
--   approval_state — human gate (only moves via explicit endpoints)
--
-- The interlock CHECK constraint is the fill-and-stop safety backstop:
-- status cannot reach 'approved' or 'submitted' unless approval_state is
-- 'approved'. Enforcement is application-layer-first; this CHECK is the
-- belt-and-braces guard.

CREATE TABLE IF NOT EXISTS tony_drafts (
    id BIGSERIAL PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft_generated',
    approval_state TEXT NOT NULL DEFAULT 'pending_review',

    source TEXT NOT NULL DEFAULT 'photo_session',
    canonical_title TEXT,
    canonical_description TEXT,

    item_facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    pricing_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    images_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    renderings_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,

    CHECK (status IN ('draft_generated', 'needs_review', 'approved', 'submitted', 'archived', 'rejected')),
    CHECK (approval_state IN ('pending_review', 'approved', 'rejected', 'needs_changes')),
    CHECK (
        status NOT IN ('approved', 'submitted')
        OR approval_state = 'approved'
    )
);

CREATE INDEX IF NOT EXISTS idx_drafts_status_created
    ON tony_drafts (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_drafts_approval_state
    ON tony_drafts (approval_state);
