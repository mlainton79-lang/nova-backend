# Codex review — 6c2ff6a

## Commit reviewed

- SHA: `6c2ff6a` (full SHA in `git log`)
- Subject: `fix(diag): close DB connection on passive-path exceptions (codex P3, 5c70ce4)`
- Reviewed against: `HEAD~1` (`8004117`)

## Verdict (verbatim)

> The change closes the database connection reliably on the diagnostic Gmail debug path and does not introduce an observable regression in the reviewed diff.

## Findings (verbatim)

_None. Clean bill._

---

## Session report

Chain of bricks + Codex reviews shipped in this session, in commit order:

| Commit | Type | Subject | Codex outcome |
|---|---|---|---|
| `caf1c93` | feat | council: config membership, grounding contract, health envelope | 2 × P2 (health envelope not in schema; xai not aliased) |
| `df8433c` | fix | council: expose council_health in schema, accept xai alias | clean bill |
| `031b8f1` | fix | gap-detector: advice guard, safe-mode falls through, honour provider disable | 1 × P3 (test-file naming — false positive against repo's `_test_*` convention) |
| `1ac45d2` | fix | gmail: dead tokens raise not vanish, search block names unreadable accounts | 1 × P2 (fetch_per_account_literal swallows GmailApiError) |
| `169e008` | fix | gmail: fetch_per_account_literal surfaces reauth as explicit block, not None | clean bill |
| `f1b2f96` | feat | family facts computed at runtime, scoped DIAG_TOKEN | 1 × P2 (diag scope reached refresh_access_token side-effect path) |
| `5c70ce4` | fix | diag: diag scope gets passive-only /gmail/debug | clean bill on scope split; 1 × P3 (DB conn leak on exception) |
| **`6c2ff6a`** | fix | diag: close DB connection on passive-path exceptions | **clean bill (this review)** |

Verdict artifacts landed for every review at `docs/reviews/<short-sha>.md` per the standing rule established mid-session.

### Session pattern

Each brick followed the same protocol: sandbox-validated patch → apply → validate (compileall + suite runners, PRoot env failures accepted) → commit → push → Codex review → verdict artifact → push. Every Codex finding was either closed by a same-session follow-up brick or explicitly deferred with rationale. No production-facing Codex finding is currently open.

### Notable behavioural outcomes

- **Council**: `COUNCIL_MEMBERS` env dial now honoured with xai→grok alias; per-provider `council_health` envelope now reaches the API surface via the `CouncilResponse` schema.
- **Gap detector**: advice/planning questions no longer misclassified as capability gaps; safe-mode degrades to answering, not refusing; disabled-provider status now short-circuits classifier.
- **Gmail visibility**: dead refresh tokens raise instead of returning `[]`; unreadable accounts named in prompt context both in the fan-out block and the per-account literal path; nothing silently drops.
- **Diagnostics**: new `DIAG_TOKEN` scope with a passive-only contract on `/gmail/debug` (DB read only, no refresh, no writes, no external calls); enforced by source-contract test guarding against future regressions; connection-lifetime handled through nested try/finally on the passive path.
