# Next-session investigation — possible fabricated conversation logs

**Date raised:** 2026-06-03
**Status:** flagged, not investigated. Do not deep-dive without explicit time-box.
**Severity:** unclear — could be benign (seed/test data) or serious (system fabricating user history)

## Summary

Two database rows were found referencing a taxi-booking conversation. Matthew confirmed he has **never asked Nova to book a taxi, ever**. The rows are not real user requests.

## Rows

### `tony_learning_log` id 27

```
created_at  2026-06-01 16:27:51.380293 UTC
score       4
provider    gemini
message     Can you book me a cab to the airport?
reply       No, I can't do that. I can't book things for you directly.
lesson      Offer to find a cab booking service/app.
```

### `tony_capability_requests` id 3

```
started_at        2026-06-01 16:50:05.631204 UTC   (23 min after id 27)
capability_name   book_taxi
status            refused_governor → set to "removed" 2026-06-03 by Matthew
attempt_count     0
user_message      Can you book me a taxi to Sheffield train station for 3pm tomorrow?
description       Integrate with a taxi booking service API to allow booking and managing taxi rides.
last_error        governor: approval_required_but_not_provided
```

The phantom `tony_capability_requests` row was cleared on 2026-06-03 (status → `removed`) so it doesn't keep haunting the gap-detector queue. The `tony_learning_log` row id 27 was **left in place** as evidence.

## How this surfaced

`meta_cognition` ran at 01:03:31 UTC on 2026-06-03. It read these two rows (id 27 was in `review_recent_conversations`'s 48h window, sorted by lowest score → near the top) and concluded Tony had been "falsely denying my own capabilities, like telling him I couldn't book a cab when I should be taking action." That self-assessment landed in `tony_alerts` id 492968 and `tony_behaviour_rules` ids 151, 152.

So the meta_cognition drift signal was *real* and useful, but the underlying conversation it was reasoning about appears not to have happened. Tony is currently self-correcting against fabricated evidence.

## Why this matters

The anti-fabrication / retrieval-guard layer (commits `38a604c feat(council,chat-stream): retrieval-intent fabrication guard (Layer 2)`, `7081453 fix(prompts): sharpen anti-fabrication guard for absent context blocks (Layer 1)`, `a94dcec fix(prompts): close 'live context block' denial gap in Council synthesis`) exists specifically to prevent invented context from entering the response path. If conversation history itself is being fabricated upstream of these guards, the guards can't help — they trust their inputs.

## What to check next session (do not do tonight)

1. **Is `tony_learning_log` id 27 genuinely user-originated, or written by a script/test/seed/agent?** Check `provider`, surrounding rows (ids 25, 26, 28, 29), and whether 16:27 UTC on 2026-06-01 matches any known automated run.
2. **Same for `tony_capability_requests` id 3.** Where in the codebase does `start_autonomous_build` get called? Was there a chat row preceding the 16:50 capability detection?
3. **Are there other phantom rows?** Spot-check `tony_learning_log` for low-score rows whose `message` Matthew doesn't recognise. Search for any seed/fixture scripts in `app/`, `tests/`, or migrations.
4. **Does any path write to `tony_learning_log` that isn't tied to a real user request?** e.g. capability evaluation harness, self-play, scheduled introspection runs.

## What to **NOT** do without thinking

- Do not mass-purge `tony_learning_log` rows. Other entries are presumably real and feed `weekly_learning_synthesis` and `meta_cognition`.
- Do not just assume "seed data" without verifying. If it is seed data, where is the seeding script? If it isn't, the question is much bigger.
- Do not act on `meta_cognition`'s self-assessment from 2026-06-03 as if it were grounded — the underlying behaviour rules (ids 151, 152) are themselves built on the phantom conversation. Consider whether they need to be marked dormant.

## Linked artifacts

- `app/core/meta_cognition.py` — how the LLM dict was extracted
- `app/core/gap_detector.py` — how `tony_capability_requests` is populated
- `app/core/learning.py` — how `tony_learning_log` is populated
- Worker run: `tony_worker_log` row from 2026-06-03 01:03:31 UTC task_name=meta_cognition
- Drift alert: `tony_alerts` id 492968
- Behaviour rules: `tony_behaviour_rules` ids 151, 152
