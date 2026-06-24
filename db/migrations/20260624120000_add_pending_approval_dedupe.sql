-- Deduplicate active approval requests for the same stable action.
-- Runtime creation remains in app/core/approval_lock.py per project convention.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_tony_pending_approvals_awaiting_action
    ON tony_pending_approvals(capability_key, action_hash)
    WHERE status = 'awaiting';

COMMIT;
