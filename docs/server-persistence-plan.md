# Server-side chat persistence — design plan (Option D)

## Current state

Chats live entirely on Android (`ChatHistoryStore.kt`, SharedPreferences JSON). The backend has no concept of a chat session: no `chat_id`, no per-turn linkage, no `chat_sessions` table. `request_logs` persists one row per request with 500-char truncation and no chat_id.

Council raw outputs (per-brain round 1, round 2, challenge, skipped-brain error strings) are returned in the HTTP response then **discarded server-side**. Android captures round1/round2/challenge into `ChatEntry.debugData`; the top-level `failures` dict is dropped at parse time and is lost forever.

## Gap

- No server-side enumeration of chats.
- No turn history independent of on-device storage (device wipe = total loss).
- No Council deliberation archive, so skipped-brain error reasons are unrecoverable for historical turns.

Commit `f84ee24` ships a formatter that works around this (Option 1C: Android POSTs its own chat JSON). It's an interim while the source-of-truth lives on one device.

## Proposed architecture

**`chat_turns`** — one row per user↔tony exchange:
- `id` (serial PK), `chat_id` (text, Android's existing UUID)
- `turn_number` (int, monotonic within chat)
- `user_message`, `user_message_at`, `assistant_reply`, `assistant_reply_at`
- `route` (`auto→groq`, `council`, `command`, etc.)
- `system_prompt_snapshot` (text, nullable — optional capture)
- `document_filenames` (text[]) — filenames only, never bytes
- `created_at`; index on `(chat_id, turn_number)`

**`council_turns`** — FK to `chat_turns`:
- `id`, `chat_turn_id`
- `deciding_brain`, `round1` (jsonb), `round2_refined` (jsonb)
- `challenge`, `providers_used` (text[])
- `providers_failed` (jsonb: `{brain: error_string}`) ← closes the `failures` gap
- `latency_ms`, `created_at`

## Migration strategy (Android → server sync)

1. Android `ChatSyncService`: on every new turn, background `POST /api/v1/chat/turns/sync`. Server writes to `chat_turns` (+ `council_turns` when applicable). Fire-and-forget; UI never blocks.
2. `chat_stream` / `council` endpoints return the council debug block so the client's sync can forward it, closing the `failures` capture gap at source.
3. One-off `POST /api/v1/chat/backfill` to import existing Android history. Pre-migration skipped-brain errors stay missing — that data is gone.
4. Transcript endpoint refactor: `GET /api/v1/chat/{chat_id}/transcript?format=markdown|json` reads from the new tables. Keep the Option 1C POST formatter around for one release as fallback.

## Open questions

- **Auth scope**: single-user (DEV_TOKEN) today. Multi-tenant ever? Schema needs `user_id` from day one if so.
- **Prompt snapshotting**: capturing the full dynamic system prompt per turn is 3-8 KB extra per row. On by default or opt-in?
- **Retention**: 30 days, 1 year, forever? Server-side truth makes us a data custodian.
- **Schema shape**: JSONB for round1/round2 is quickest to ship; per-brain rows would enable analytics later.

## Rough sizing

- Average turn: ~2 KB text + up to ~20 KB council debug ≈ 22 KB.
- Realistic ceiling: < 50 MB total across a year of heavy usage.
- Implementation effort: ~2 days. Schema + two ingest endpoints + one transcript refactor + Android `ChatSyncService`. No architectural rework required.
