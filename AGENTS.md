# AGENTS.md — Nova backend conventions for AI coding agents

This file is the cross-tool open standard ([agents.md](https://agents.md)) that AI coding agents read at the start of every session to learn project conventions. If you're an agent (Codex, Claude Code, Cursor, anything else) opening a session against this repo, read this file completely before suggesting code, reviewing diffs, or running commands.

If a convention here contradicts something in `HANDOVER.md`, `HANDOVER.md` wins for credentials/infrastructure facts and this file wins for code conventions. If something here contradicts your own training-derived "best practice," this file wins — Nova's conventions are hard-won and deliberately non-standard in a few places.

---

## Project overview

Nova is a single-user personal AI assistant. **nova-backend** is the Python/FastAPI HTTP backend deployed on Railway, backed by a single Railway Postgres instance with pgvector. There is exactly one user (Matthew Lainton); there will never be a second user, a tenant, or an org. Multi-user concerns (`user_id` columns, per-tenant partitioning, row-level security, OAuth-per-user fan-out) are explicitly out of scope and should never be proposed even when "obviously good practice." The companion repos are **nova-android** (Kotlin client running on Matthew's phone, primary surface) and **nova-docs** (operational evidence + briefs + architecture memos; this is where session briefs and code-review write-ups live).

The backend hosts the chat surface (a multi-provider "Council" pattern that fans out across OpenAI/Anthropic/Gemini/Groq/Mistral/etc.), a sizable set of background "organs" (memory consolidation, goal extraction, financial intelligence, email triage, etc., most living under `app/core/`), a Gmail integration, and a growing selling-operator pipeline (eBay, Discogs, musicMagpie, WoB via REST APIs; Vinted via Android UI automation). The `web` service auto-deploys on push to `mlainton79-lang/nova-backend@main`; `railway up` from a local checkout remains supported as an alternative path (see "Deploy verification" below).

nova-docs is documentation-only — briefs, reviews, architecture memos. Never put runnable code there. Production code lives in nova-backend (Python/FastAPI) and nova-android (Kotlin client).

---

## Standing architecture rules

These are non-negotiable. Several exist because of incidents that cost real time to debug — propose changes to them only with explicit user sign-off.

- **psycopg2 only.** No SQLAlchemy, no asyncpg, no databases/encode, no ORMs of any kind. Connect per call with `psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require", connect_timeout=10)`, use the connection inside a `try/finally` that closes it, and prefer `conn.autocommit = True` + `with conn.cursor() as cur:` for single-statement work. Connection pooling has been deliberately avoided because the workload doesn't need it and pools complicate cron + worker process boundaries.
- **Single-user system — never add `user_id`.** Tables enforce the single-user invariant via `UNIQUE` constraints on the natural discriminator (`UNIQUE (environment)` on `tony_ebay_tokens`, `UNIQUE (account)` on integration tables, `UNIQUE (email)` on `gmail_accounts`). Adding `user_id NULL` "for future flexibility" is forbidden — it accumulates ambiguity and the future it preserves will never arrive.
- **Table prefix `tony_*` for app-owned tables.** Examples: `tony_selling_jobs`, `tony_selling_job_events`, `tony_ebay_tokens`, `tony_ebay_oauth_states`, `tony_facts`, `tony_living_memory`, `tony_episodic_memory`. The few non-prefixed tables (`gmail_accounts`, `run_events`, `request_logs`, `semantic_memories`) are pre-convention and left alone. New tables get the prefix.
- **`record_run_event` MUST NEVER raise.** Every persistence path, every external API call, every background-task entry point catches `Exception`, calls `record_run_event(subsystem='...', event_type=..., severity=..., error_class=type(e).__name__, error_message=str(e), metadata={...})`, and returns `None` / `False` / `[]` to the caller. The helper itself is defensively wrapped so a logging failure can't propagate. The contract: no failure path is allowed to surface as a FastAPI 500 unless the surface is genuinely synchronous user-facing (chat endpoint, etc.) — and even then the failure must be logged via `record_run_event` *before* the HTTPException is raised.
- **Subsystem naming uses dotted prefixes.** Examples in active use: `startup.*`, `worker.*`, `cron.*`, `api.<resource>` (e.g. `api.gmail`), `provider.<name>` (e.g. `provider.openai`), `memory.<type>` (e.g. `memory.tony_facts`), `selling.<platform>.<subaction>` (e.g. `selling.ebay.oauth`). When adding a new subsystem, follow the closest existing prefix; don't invent a new top-level.
- **Leaf imports — the import graph is a DAG.** `app/core/` modules don't import from `app/api/`. `app/selling/` doesn't import from `app/api/`. `app/observability/` imports from nothing else in `app/`. The router (`app/api/v1/router.py`) is the one place allowed to import broadly. Circular imports break Railway's autoloader silently — the app boots but routes 404 with no error in logs.
- **Never name a module inside a package `types.py` or `enum.py`.** Stdlib shadow trap — `from enum import Enum` inside a module sitting next to a local `enum.py` will pick up the local file and explode in unpredictable places. Use `event_types.py`, `job_status.py`, etc.
- **`log_request` is NOT async.** It's a sync helper used inside async handlers via the standard pattern: just call it, don't `await` it. The Logger module name is `log_request` (not `log_interaction`).
- **The Council endpoint returns a `dict`.** Use `.get('key')` defensively; don't try to dataclass-deserialize it. Per-brain failures are recorded inside the dict under `failures: {brain_name: error_string}` and the response shape varies depending on whether round-2 challenge fired. Treat it as semi-structured JSON.
- **Migrations are versioned SQL files in `db/migrations/`.** Naming: `YYYYMMDDHHMMSS_<short_description>.sql`. One migration per atomic schema change (related tables in one file is fine; unrelated tables in one file is not). Migrations exist as versioned SQL files for audit/history, but production schema is enforced via `init_<feature>_tables()` functions called from `app/api/v1/router.py`'s `_inits` list at startup using `CREATE TABLE IF NOT EXISTS`. There is no separate migration runner (no Alembic, no Flyway). Pair every migration SQL file with its init function — the init function is the source of truth that prod actually executes.
- **Startup init pattern.** New table-owning modules expose `init_<feature>_tables()` that does the `CREATE TABLE IF NOT EXISTS` / index creation. Wire it into `app/api/v1/router.py`'s `_inits` list (the module-path + function-name + label tuple). Init failures are caught + printed, never raised.

---

## Chat surface and Tony persona

User-facing chat flows go through a multi-provider Council pattern (fan-out across OpenAI/Anthropic/Gemini/Groq/Mistral) returning a dict with per-provider responses + `failures: {brain_name: error_string}` for any provider that errored. The user-facing AI persona is named "Tony" — when reviewing prompt-engineering or chat-flow changes, preserve the Tony voice (direct, warm, dry, short British English sentences, no "son"/"lad"/"mate" filler). The persona is intentionally personal — it carries the voice of Matthew's late father. Don't propose making it "more professional" or "more enterprise."

---

## File editing discipline

- **Edit tool preferred for `.py` files** — direct-to-disk edits are tracked in git and trivially reviewable in the diff.
- **`.kt` and `.xml` files (nova-android repo) get full-file paste in AIDE.** Never `sed`, never bulk terminal manipulation. AndroidIDE's editor is the source of truth for those files; out-of-band edits cause merge corruption that's hard to recover from.
- **AIDE / Android Code Studio MUST be closed before any `.kt` or `.xml` edit from an agent.** Open editor + concurrent file write = silent overwrite when the user next saves in AIDE.
- **Never use the Edit tool on secret-bearing lines.** The Edit tool echoes `old_string` into the conversation transcript, which would write a credential into the session log. For any line containing a credential, API key, or token, edit through AIDE / Matthew's local editor instead.
- **Never delete or rewrite `.bak.*` files.** They're checkpoints from earlier sessions (`status.py.bak.dbg_status_a1`, `main.py.bak.r1_3_part2_subitem1`, etc.). Leave them alone unless Matthew explicitly asks for cleanup.

---

## Secret handling

- **Never echo or print full secret values.** This includes in tool output, in commit messages, in PR descriptions, in test fixtures, in error messages, in `record_run_event` metadata, and in HTML response bodies (especially OAuth callback success pages).
- **For Railway secret reads use `railway variables --json`** and process with Python `len()` / `[:N]` slicing to report length + prefix only. NEVER use `railway variables --kv` — it prints raw `KEY=VALUE` pairs in plaintext, which lands in the session transcript.
- **Never read or print shell startup files.** `.bashrc`, `.zshrc`, `.profile`, `.env`, `.envrc` — all forbidden. `env` without filtering is also forbidden (use `env | grep -iE 'pattern' | sed 's/=.*/=<set>/'` if you need to check whether something is set).
- **Token-rotation events go in nova-docs evidence**, never in commit messages or transcript text. The event itself ("PAT rotated 2026-05-25") is fine to record; the token value never is.
- **Secret-bearing variables — length + prefix only.** App IDs, Cert IDs, API keys, OAuth client secrets, refresh tokens. Example: `len=40 prefix='Matt'`.
- **Public OAuth identifiers — safe to log fully.** eBay RuNames, well-known Google/Microsoft client IDs that are public-by-design. When in doubt, treat as secret.
- **The GitHub PAT for nova-backend pushes lives in Railway Variables on the `web` service as `GITHUB_PAT`.** It is NOT in any local file, NOT in `~/.gitconfig`, NOT in `~/.netrc`. Extract via `railway variables --kv` is forbidden; use `--json` + Python.

---

## Deploy verification (Railway)

- **The `web` service auto-deploys on push to `mlainton79-lang/nova-backend@main`** (GitHub source connected 2026-06-16 via Railway MCP). `railway up` from a local checkout is still supported as a parallel path — useful for deploying un-pushed work or testing a branch — but the default is now: commit, push, wait. Every push to `main` triggers a fresh build.
- **`railway up` exit code is NOT reliable.** It can exit 0 while the build still fails, or exit non-zero on transient CLI issues while the build actually completes. Always three-signal verify (applies to both push-driven and `railway up` deploys):
  1. New deployment ID returned by `railway status --json` (different from the previous one).
  2. HTTP 200 on `https://web-production-be42b.up.railway.app/api/v1/health`.
  3. A `worker_started` (or comparable startup) row appearing in `tony_run_events` with a `created_at` after the deploy timestamp.
- **Variable changes auto-trigger redeploys of the current built image.** Not a fresh build, just a relaunch with the new env. This means: adding `EBAY_*` Variables before the code that consumes them lands is *harmless* — the redeploy is a no-op for the application, the variables just sit there unused until code references them.
- **The `web` service is the only currently active service.** `peaceful-harmony` is scaled to 0 replicas (image preserved, available for manual `railway run` invocation). Cron runs `think_worker.py` on its own schedule. Don't deploy code intended for the cron via the web service path or vice versa.
- **`backend_commit_sha` only reports `"unknown"` after `railway up` deploys** (because `RAILWAY_GIT_COMMIT_SHA` isn't auto-populated for CLI deploys). Push-driven deploys populate it correctly. Use deployment ID + timestamp as the fallback identifier when SHA is `unknown`.

---

## Commit message format

- **Type prefix:** `feat(scope)`, `fix(scope)`, `docs(scope)`, `refactor(scope)`, `chore(scope)`.
- **Scope is the affected area:** `feat(selling)`, `fix(council)`, `docs(evidence)`, `docs(reviews)`, `fix(ebay-oauth)`, `chore(deps)`.
- **Subject after the prefix is short, present tense, no trailing period.** Aim for under 70 chars.
- **Body explains WHY, not WHAT.** The diff already shows what changed. The body answers: what user-facing behaviour does this change, what prompted it, what won't break that someone might fear would break. Wrap at ~72 chars.
- **Co-author trailer for agent commits:** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (or the equivalent Codex / agent identifier). One trailer per agent that contributed.
- **Never amend a published commit.** If a pre-commit hook fails or you realise the commit message is wrong, make a new commit on top (`fix(scope): correct previous commit message`) — never `git commit --amend` on something that's been pushed.

---

## Two-brain / Three-tool workflow

Matthew runs Nova with three AI tools, each with a defined role. Stay in your lane.

- **Claude Code is the primary implementer.** Operates with project-memory continuity across sessions, owns the leaf-import discipline, the `record_run_event` discipline, dotted subsystem naming, the migration + init-function pattern, and end-to-end feature work from design through commit + push.
- **Codex (GPT-5.5 via the Codex CLI) is the security reviewer and command-line workhorse.** Reviews are **mandatory before push** for any work touching credentials, OAuth, refresh tokens, or new external API surfaces. **Recommended** for non-trivial architecture changes (new tables, new modules, anything cross-package). **Optional** for trivial work (typo fixes, doc updates, single-line bug fixes).
- **ChatGPT (separate browser, not in any CLI) handles longer-form architectural review** and three-brain consultations on hard decisions. Matthew dispatches to ChatGPT manually when a hard decision benefits from a perspective outside the Claude-Code-and-Codex pair.
- **Matthew is the human dispatcher** routing work between the three tools and making final go/no-go calls on production deploys.
- **Never two tools editing the same file simultaneously.** When handing off mid-feature, finish your edits, commit (or stash), and explicitly hand off via a brief in `nova-docs/ops/evidence/YYYY-MM-DD/`. The next tool reads the brief, picks up state, and resumes.

---

## Writing reviews (for Codex)

If you are Codex reviewing a Claude Code diff (or any agent reviewing another agent's diff), write the review as a markdown file at:

```
nova-docs/ops/reviews/YYYY-MM-DD/codex-review-<short-description>.md
```

(Substitute `codex-review-` with your agent identifier if you're a different reviewer.)

Commit it to **nova-docs** (not nova-backend) with message:

```
docs(reviews): Codex review — <short description>
```

**Do not modify the code being reviewed.** The review is read by the implementer (Claude Code or Matthew directly) who addresses each point, iterates, and pushes a fix commit. Iteration is cheap; reviewer-and-implementer being the same agent is a known anti-pattern that erodes the review's value.

Review structure expected:

1. **Verdict line at top** — `APPROVE` (ready to commit), `APPROVE WITH NITS` (mergeable but address noted points in a follow-up), `REQUEST CHANGES` (don't push until fixed), `BLOCK` (architectural concern — pause and consult Matthew before proceeding).
2. **Findings** — numbered list, each finding has: severity (blocker / major / minor / nit), location (`path/to/file.py:line`), the issue stated specifically, the suggested fix.
3. **Out-of-scope observations** — things you noticed that aren't in this diff but should be tracked. Separate section so the implementer can triage them into follow-up work without conflating with the current review.

If you find no issues, still write a brief review file confirming "APPROVE — no findings, reviewed against AGENTS.md conventions." A silent review is indistinguishable from a skipped review.

---

## Re-grounding in long sessions

If your session has been running for more than ~30 minutes, or you're picking up a thread mid-task, re-read this file. Session drift is real — agents subtly converge on training defaults the longer they go. Re-grounding is cheap and prevents subtle convention erosion.

---

## When you (the agent) are unsure

Ask. Matthew prefers a clarifying question over a confidently-wrong implementation, especially for: secret-bearing code paths, schema decisions, anything touching Railway production state, and anything that would deviate from the standing architecture rules above. The cost of a clarifying message is one round-trip; the cost of a wrong implementation that has to be reverted from production is much higher.
