# Android repo status — 2026-07-23 (frontend cycle)

Update to the morning report (`ANDROID-STATUS-2026-07-23.md`). Push auth is holding; the frontend brief landed with two codex feedback loops.

## Current HEAD

`bcd6455 docs: codex review session report for 7482cf0 (clean pass)` on `master`, tree clean.

## Frontend brief — landed

Four TARGETs from the brief: `NovaApiClient.kt` model+parsing, `MainActivity` `debugJson`, debug panel renderer, brain picker trim.

**Three landed on first pass. Picker trim reverted after codex flagged a regression. One follow-up fix on a pre-existing bug.**

Commits on `master` since the morning push-auth work (`2743968`):

```
bcd6455 docs: codex review session report for 7482cf0 (clean pass)
7482cf0 fix(ui): stop duplicating user bubble in on-device path (codex P2 on bb0aec7)
99d6d56 docs: codex review session report for bb0aec7 (P2 on pre-existing on-device duplicate)
bb0aec7 revert(ui): restore Auto and Local Tony to brain picker (codex P2 on ed78861)
46e4c9b docs: codex review session report for ed78861 (P2 on picker trim)
ed78861 feat(ui): render council_health + dark seats, fix failures parsing, trim picker to live brains
```

### What's live in the app now

- **`council_health` + dark seats rendered.** New `CouncilHealthData` / `DarkSeat` types parse the top-level `council_health` envelope (present on every council reply per `app/providers/council.py::_build_council_health`). Debug panel now shows `🪑 N/M seats responded · chair: X` and `🌑 Dark: gemini (RateLimitError), grok (DisabledViaEnv)`. Emitted even when `debug=false` if the envelope is present — degraded responses no longer render as a blank debug panel.
- **Typed failures parsing (bug fix).** Backend ships `failures` as `{provider: {stage, error_class, message}}`. Prior Kotlin used `f.optString(k)` on the value, which silently coerced the object to `""` — a real silent contract drift. Now parsed as `CouncilFailure(errorClass, message, stage?)`, rendered as `"claude: RateLimitError — 429 too many requests"` in both the failure banner and the debug panel's `── Failures ──` block.
- **`debugJson` marshalling includes both.** ChatHistoryStore's stored debug blob now round-trips typed failures + council_health, so the debug panel renders correctly from cold history too.
- **Picker unchanged.** Auto and Local Tony remain in the picker (see codex cycles below).

### Codex cycles

1. **`ed78861`** — first push. Codex flagged **P2** on picker trim: filtering `AUTO` + `LOCAL_TONY` out of `showBrainPicker()` made them unreachable for new users, while both modes still worked in the routing paths and `showOnDeviceModelStatus()` still instructed *"Switch to 'Local Tony' brain mode to use it offline"*. Real functional regression. Report: `docs/reviews/ed78861.md` in the android repo.
2. **`bb0aec7`** — reverted just the picker filter. Codex passed the revert but flagged **P2** on a **pre-existing** duplicate-append bug re-exposed by restoring the picker entry: `processOnDevice()` at `MainActivity.kt:2388` was writing the user message a second time (caller `sendCurrentMessage()` already writes at `:736`). Every Local Tony exchange rendered two identical user bubbles. Pre-dates this branch. Report: `docs/reviews/bb0aec7.md`.
3. **`7482cf0`** — deleted the duplicate append. Codex clean pass. Report: `docs/reviews/7482cf0.md`.

Session reports live in `nova-android/docs/reviews/` — reachable now that android push works.

## Outstanding

- **AAPT2 x86_64 on ARM PRoot** blocks local `bash gradlew :app:compileDebugKotlin` before it reaches Kotlin compile. Same env issue that pre-existed this branch. Type-critical change was `Map<String, String>` → `Map<String, CouncilFailure>`, both call sites updated in the same diff. No compile-time validation possible in this sandbox; CI on GitHub is the real gate.
- **`showOnDeviceModelStatus()` copy** at `MainActivity.kt:1556` is now correct again (picker restored). No action needed unless the on-device feature is being retired — in which case the picker trim + copy update should ship together, not separately.

## Backend context (unchanged from morning, plus one)

- Push auth restored on both repos this morning (`358f36b` here, matching remote).
- **Self-check chain fix landed today too** — separate work: `1e02844` (chain perpetuation) + `583cd47` (codex P2, record chain-scheduling failures via `run_events`). Both got clean codex passes after their respective fixes. Reports at `docs/reviews/1e02844.md`, `docs/reviews/583cd47.md`. Deploy-dependent gaps in the morning heartbeat (Tue/Thu with no task) are closed.
