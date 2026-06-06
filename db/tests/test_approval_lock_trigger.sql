-- Trigger-behavior tests for tony_pending_approvals_guard.
--
-- Wedged into .github/workflows/restore-drill.yml per the chosen test
-- convention for this brick. Runs against the restored scratch Postgres
-- after the migration in db/migrations/20260606120000_create_approval_lock_tables.sql
-- (or its mirror init function) has created the tables and trigger.
--
-- Each test exercises the trigger and either:
--   - asserts the trigger RAISES with the expected message (negative tests)
--   - asserts the operation SUCCEEDS (positive tests)
-- If any test fails, the DO block raises and psql exits non-zero — the
-- workflow then fails the job.
--
-- The whole file runs inside one transaction with ROLLBACK at the end, so
-- no test rows persist (even though the scratch DB is throwaway).
--
-- Mapping to alpha-design adversarial test numbers (alpha §"Adversarial tests"):
--   T14 — INSERT status=approved + grant_id=NULL                        → raises
--   T15 — INSERT status=awaiting + approved_at populated                → raises
--   T16 — INSERT status=denied + grant_id populated                    → raises
--   T17 — UPDATE: status approved → awaiting (illegal state transition) → raises
--   T18 — UPDATE: grant_id changed to different non-NULL value          → raises
--   T19 — UPDATE: immutable field (action_hash) changed                 → raises
--   T20 — UPDATE: mutate immutable pending_id (PK)                     → raises
--                  (covers a different immutable column than T19's
--                  action_hash — spot-coverage on two of the seven
--                  immutable fields, not exhaustive proof)
--   T+  — POSITIVE: all-at-once awaiting → approved UPDATE              → succeeds
--                  (alpha-r2 #1: trigger MUST permit this single UPDATE)

BEGIN;

\echo === tony_pending_approvals_guard trigger test suite ===

-- ---------------------------------------------------------------------------
-- Setup: two enrolled test devices (FK targets for approved_by / denied_by).
-- Fixed UUIDs so each test can reference them. ON CONFLICT DO NOTHING so the
-- script is re-runnable.
-- ---------------------------------------------------------------------------
INSERT INTO tony_approval_devices (device_id, device_name, secret_hash, status)
VALUES
    ('00000000-0000-0000-0000-00000000000a'::uuid,
     'test_device_A',
     'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
     'active'),
    ('00000000-0000-0000-0000-00000000000b'::uuid,
     'test_device_B',
     'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
     'active')
ON CONFLICT (device_id) DO NOTHING;


-- ===========================================================================
-- T14  INSERT status=approved with grant_id=NULL  →  trigger raises
-- ===========================================================================
DO $$
BEGIN
    BEGIN
        INSERT INTO tony_pending_approvals (
            pending_id, capability_key, action_hash, action_snapshot,
            status, expires_at, approval_challenge,
            approved_by_device_id, approved_at,
            approval_challenge_used_at, grant_id
        ) VALUES (
            gen_random_uuid(), 'gmail_send',
            decode(repeat('14', 32), 'hex'), '{}'::jsonb,
            'approved', NOW() + INTERVAL '1 hour',
            decode(repeat('14', 16), 'hex'),
            '00000000-0000-0000-0000-00000000000a'::uuid, NOW(),
            NOW(), NULL  -- grant_id NULL — should be rejected
        );
        RAISE EXCEPTION 'T14 FAILED: INSERT status=approved + grant_id=NULL was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'status=approved requires' THEN
                RAISE NOTICE 'T14 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T14 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T15  INSERT status=awaiting with approved_at populated  →  trigger raises
-- ===========================================================================
DO $$
BEGIN
    BEGIN
        INSERT INTO tony_pending_approvals (
            pending_id, capability_key, action_hash, action_snapshot,
            status, expires_at, approval_challenge,
            approved_at  -- non-NULL on an awaiting row — should be rejected
        ) VALUES (
            gen_random_uuid(), 'gmail_send',
            decode(repeat('15', 32), 'hex'), '{}'::jsonb,
            'awaiting', NOW() + INTERVAL '1 hour',
            decode(repeat('15', 16), 'hex'),
            NOW()
        );
        RAISE EXCEPTION 'T15 FAILED: INSERT status=awaiting + approved_at non-NULL was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'status=awaiting requires all companion fields NULL' THEN
                RAISE NOTICE 'T15 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T15 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T16  INSERT status=denied with grant_id populated  →  trigger raises
-- ===========================================================================
DO $$
DECLARE
    v_pending UUID := gen_random_uuid();
    v_grant   UUID := gen_random_uuid();
BEGIN
    BEGIN
        INSERT INTO tony_pending_approvals (
            pending_id, capability_key, action_hash, action_snapshot,
            status, expires_at, approval_challenge,
            denied_by_device_id, denied_at,
            approval_challenge_used_at, grant_id
        ) VALUES (
            v_pending, 'gmail_send',
            decode(repeat('16', 32), 'hex'), '{}'::jsonb,
            'denied', NOW() + INTERVAL '1 hour',
            decode(repeat('16', 16), 'hex'),
            '00000000-0000-0000-0000-00000000000b'::uuid, NOW(),
            NOW(),
            v_grant  -- grant_id non-NULL on a denied row — should be rejected
        );
        RAISE EXCEPTION 'T16 FAILED: INSERT status=denied + grant_id non-NULL was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'status=denied requires approved_at, approved_by_device_id, grant_id all NULL' THEN
                RAISE NOTICE 'T16 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T16 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T17  UPDATE: illegal state transition  approved → awaiting  →  trigger raises
--
-- Setup: insert an awaiting row, mint a real grant for it, then drive the
-- awaiting → approved transition properly (positive path). Then attempt the
-- reverse (approved → awaiting) — this must raise.
-- ===========================================================================
DO $$
DECLARE
    v_pending UUID := gen_random_uuid();
    v_grant   UUID := gen_random_uuid();
BEGIN
    -- (a) create the awaiting row
    INSERT INTO tony_pending_approvals (
        pending_id, capability_key, action_hash, action_snapshot,
        status, expires_at, approval_challenge
    ) VALUES (
        v_pending, 'gmail_send',
        decode(repeat('17', 32), 'hex'), '{}'::jsonb,
        'awaiting', NOW() + INTERVAL '1 hour',
        decode(repeat('17', 16), 'hex')
    );
    -- (b) mint the grant (FK target for the all-at-once approve update)
    INSERT INTO tony_action_grants (
        grant_id, capability_key, action_hash, pending_action_ref,
        expires_at
    ) VALUES (
        v_grant, 'gmail_send',
        decode(repeat('17', 32), 'hex'), v_pending,
        NOW() + INTERVAL '30 minutes'
    );
    -- (c) atomic approve: all companions set in ONE UPDATE
    UPDATE tony_pending_approvals
       SET status = 'approved',
           approval_challenge_used_at = NOW(),
           approved_by_device_id = '00000000-0000-0000-0000-00000000000a'::uuid,
           approved_at = NOW(),
           grant_id = v_grant
     WHERE pending_id = v_pending;
    -- (d) now attempt the illegal reverse
    BEGIN
        UPDATE tony_pending_approvals
           SET status = 'awaiting'
         WHERE pending_id = v_pending;
        RAISE EXCEPTION 'T17 FAILED: status=approved → awaiting was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'invalid status transition' THEN
                RAISE NOTICE 'T17 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T17 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T18  UPDATE: grant_id changed to different non-NULL value  →  trigger raises
-- (Setup as T17: row already approved with v_grant. Attempt to change
-- grant_id to a different UUID.)
-- ===========================================================================
DO $$
DECLARE
    v_pending UUID := gen_random_uuid();
    v_grant1  UUID := gen_random_uuid();
    v_grant2  UUID := gen_random_uuid();
BEGIN
    -- Setup: awaiting row + grant1 + approve with grant1
    INSERT INTO tony_pending_approvals (
        pending_id, capability_key, action_hash, action_snapshot,
        status, expires_at, approval_challenge
    ) VALUES (
        v_pending, 'gmail_send',
        decode(repeat('18', 32), 'hex'), '{}'::jsonb,
        'awaiting', NOW() + INTERVAL '1 hour',
        decode(repeat('18', 16), 'hex')
    );
    INSERT INTO tony_action_grants (
        grant_id, capability_key, action_hash, pending_action_ref, expires_at
    ) VALUES (
        v_grant1, 'gmail_send',
        decode(repeat('18', 32), 'hex'), v_pending,
        NOW() + INTERVAL '30 minutes'
    );
    UPDATE tony_pending_approvals
       SET status = 'approved',
           approval_challenge_used_at = NOW(),
           approved_by_device_id = '00000000-0000-0000-0000-00000000000a'::uuid,
           approved_at = NOW(),
           grant_id = v_grant1
     WHERE pending_id = v_pending;
    -- Attempt to mutate grant_id to a different value
    BEGIN
        UPDATE tony_pending_approvals
           SET grant_id = v_grant2
         WHERE pending_id = v_pending;
        RAISE EXCEPTION 'T18 FAILED: grant_id reassignment was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'grant_id is write-once' THEN
                RAISE NOTICE 'T18 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T18 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T19  UPDATE of immutable field (action_hash)  →  trigger raises
-- ===========================================================================
DO $$
DECLARE
    v_pending UUID := gen_random_uuid();
BEGIN
    INSERT INTO tony_pending_approvals (
        pending_id, capability_key, action_hash, action_snapshot,
        status, expires_at, approval_challenge
    ) VALUES (
        v_pending, 'gmail_send',
        decode(repeat('19', 32), 'hex'), '{}'::jsonb,
        'awaiting', NOW() + INTERVAL '1 hour',
        decode(repeat('19', 16), 'hex')
    );
    BEGIN
        UPDATE tony_pending_approvals
           SET action_hash = decode(repeat('ee', 32), 'hex')
         WHERE pending_id = v_pending;
        RAISE EXCEPTION 'T19 FAILED: action_hash mutation was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'action_hash is immutable' THEN
                RAISE NOTICE 'T19 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T19 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T20  UPDATE: mutate immutable pending_id (PK)  →  trigger raises
-- (T20 covers a DIFFERENT immutable column than T19's action_hash — so
-- the immutability branch is exercised on at least two of the seven
-- frozen fields. Spot-coverage, not exhaustive proof.)
-- ===========================================================================
DO $$
DECLARE
    v_pending UUID := gen_random_uuid();
BEGIN
    INSERT INTO tony_pending_approvals (
        pending_id, capability_key, action_hash, action_snapshot,
        status, expires_at, approval_challenge
    ) VALUES (
        v_pending, 'gmail_send',
        decode(repeat('20', 32), 'hex'), '{}'::jsonb,
        'awaiting', NOW() + INTERVAL '1 hour',
        decode(repeat('20', 16), 'hex')
    );
    BEGIN
        UPDATE tony_pending_approvals
           SET pending_id = gen_random_uuid()
         WHERE pending_id = v_pending;
        RAISE EXCEPTION 'T20 FAILED: pending_id mutation was ALLOWED';
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLERRM ~ 'pending_id is immutable' THEN
                RAISE NOTICE 'T20 PASS  (%)' , SQLERRM;
            ELSE
                RAISE EXCEPTION 'T20 WRONG-ERROR: %', SQLERRM;
            END IF;
    END;
END $$;


-- ===========================================================================
-- T+  POSITIVE: all-at-once awaiting → approved UPDATE succeeds
-- (alpha-r2 #1: the trigger MUST permit a single atomic UPDATE that sets
-- status='approved' + grant_id + approval_challenge_used_at +
-- approved_by_device_id + approved_at together. If this fails, the entire
-- approve flow is impossible — that was the critical Codex r2 finding on
-- alpha v2.)
-- ===========================================================================
DO $$
DECLARE
    v_pending  UUID := gen_random_uuid();
    v_grant    UUID := gen_random_uuid();
    v_status   TEXT;
    v_grant_id UUID;
BEGIN
    INSERT INTO tony_pending_approvals (
        pending_id, capability_key, action_hash, action_snapshot,
        status, expires_at, approval_challenge
    ) VALUES (
        v_pending, 'gmail_send',
        decode(repeat('99', 32), 'hex'), '{}'::jsonb,
        'awaiting', NOW() + INTERVAL '1 hour',
        decode(repeat('99', 16), 'hex')
    );
    INSERT INTO tony_action_grants (
        grant_id, capability_key, action_hash, pending_action_ref, expires_at
    ) VALUES (
        v_grant, 'gmail_send',
        decode(repeat('99', 32), 'hex'), v_pending,
        NOW() + INTERVAL '30 minutes'
    );
    -- The all-at-once transition. If the trigger raises, this DO block
    -- itself raises (no inner EXCEPTION handler), and the script aborts.
    UPDATE tony_pending_approvals
       SET status = 'approved',
           approval_challenge_used_at = NOW(),
           approved_by_device_id = '00000000-0000-0000-0000-00000000000a'::uuid,
           approved_at = NOW(),
           grant_id = v_grant
     WHERE pending_id = v_pending;
    -- Verify the post-update state matches expectations.
    SELECT status, grant_id INTO v_status, v_grant_id
      FROM tony_pending_approvals
     WHERE pending_id = v_pending;
    IF v_status <> 'approved' OR v_grant_id IS DISTINCT FROM v_grant THEN
        RAISE EXCEPTION 'T+ FAILED: post-UPDATE state wrong (status=% grant_id=%)',
            v_status, v_grant_id;
    END IF;
    RAISE NOTICE 'T+ PASS (all-at-once awaiting → approved succeeded)';
END $$;


\echo === All trigger tests PASSED ===

ROLLBACK;
