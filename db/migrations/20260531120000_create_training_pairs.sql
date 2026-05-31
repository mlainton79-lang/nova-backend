-- 20260531120000_create_training_pairs.sql
--
-- Brick 1 of Nova's distillation track — the HARVEST layer.
-- Captures every user-Tony interaction so future bricks (amplify, distil,
-- swap) have a corpus to fine-tune a Nova-owned small model on.
--
-- Wired in production via init_training_pairs_table() (app/core/training_pairs.py),
-- registered in app/api/v1/router.py _inits list. This SQL file is the
-- versioned audit-trail copy per AGENTS.md migration discipline; the init
-- function is the source of truth that production actually executes.

CREATE TABLE IF NOT EXISTS tony_training_pairs (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_input TEXT NOT NULL,
    full_context TEXT,
    history_json JSONB,
    model_answer TEXT,
    source_model TEXT,
    quality_flag TEXT,
    task_type TEXT,
    latency_ms INTEGER,
    ok BOOLEAN DEFAULT TRUE,
    error TEXT,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    data_classification TEXT DEFAULT 'private'
);

-- Curation-time indexes. quality_flag partial index is premature for v1 but
-- harmless; the rest are sensible from day one for the source_model /
-- task_type / time-bounded sampling pulls amplify+distil bricks will do.
CREATE INDEX IF NOT EXISTS idx_ttp_source_model ON tony_training_pairs(source_model);
CREATE INDEX IF NOT EXISTS idx_ttp_task_type    ON tony_training_pairs(task_type);
CREATE INDEX IF NOT EXISTS idx_ttp_created_at   ON tony_training_pairs(created_at);
CREATE INDEX IF NOT EXISTS idx_ttp_quality      ON tony_training_pairs(quality_flag) WHERE quality_flag IS NOT NULL;
