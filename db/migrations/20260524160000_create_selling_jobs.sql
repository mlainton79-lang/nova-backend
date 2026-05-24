-- Nova selling operator session 1: tony_selling_jobs + tony_selling_job_events
-- Multi-platform selling operator pattern (eBay, Discogs, musicMagpie, Vinted-via-Android-UI-Automator).
-- The existing tony_vinted_jobs schema (defined in app/core/vinted_jobs.py:31, never actually
-- created in production because peaceful-harmony was crashlooping and the lazy init never
-- triggered) is the dead-on-arrival predecessor we pivoted from. New code uses tony_selling_jobs.

CREATE TABLE IF NOT EXISTS tony_selling_jobs (
    id BIGSERIAL PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('ebay','discogs','vinted','musicmagpie','wob','other')),
    account TEXT NOT NULL DEFAULT 'default',
    item_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'starting', 'submitting', 'awaiting_human_approval',
        'posted_pending_confirmation', 'posted_confirmed',
        'failed', 'cancelled'
    )),
    platform_listing_id TEXT NULL,
    platform_listing_url TEXT NULL,
    error_message TEXT NULL,
    error_type TEXT NULL,
    requires_human_reason TEXT NULL,
    approval_state TEXT NOT NULL DEFAULT 'not_required',
    approved_at TIMESTAMPTZ NULL,
    posted_confirmed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    cancelled_at TIMESTAMPTZ NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_selling_jobs_status_created
    ON tony_selling_jobs (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_selling_jobs_platform_status_created
    ON tony_selling_jobs (platform, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_selling_jobs_platform_listing_id
    ON tony_selling_jobs (platform, platform_listing_id) WHERE platform_listing_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tony_selling_job_events (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES tony_selling_jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    message TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_selling_job_events_job
    ON tony_selling_job_events (job_id, created_at DESC);
