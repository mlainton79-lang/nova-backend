# Vinted Operator Worker

Playwright-based browser worker that fills Matthew's real Vinted Sell
form from a known draft payload, takes a screenshot of the
filled-but-not-published state, and **STOPS**. Matthew opens Vinted on
his own device, reviews, and taps Publish himself.

## ⚠ Hard rules — non-negotiable

1. **Worker NEVER clicks Publish/Upload-item/Post-item.** Enforced in
   `safety.py`. Every click in `vinted_actions.py` passes through
   `safety.assert_safe_to_proceed()` first.
2. **`verify_no_publish()` runs after every fill flow.** If the URL or
   DOM looks like a listing was just submitted, the worker logs a
   safety violation and stops.
3. **Vinted credentials live ONLY in Railway env vars.** Never in
   source, never in commit messages, never in transcripts. See
   `config.py` — credentials are read but never logged.
4. **storageState.json on Railway volume only.** Path gitignored.
   Contents never echoed.

## Required Railway env vars

Set on the worker service (separate from the web service):

```
VINTED_EMAIL=<Matthew's Vinted login email>
VINTED_PASSWORD=<Matthew's Vinted password>
DATABASE_URL=<same as web service>
```

Optional:

```
DATA_ROOT=/data            # default
BROWSER_HEADLESS=true      # default; set to "false" only for local debug
```

## Required Railway volume

Mount a Railway volume at `/data` on the worker service. The worker
will create `/data/vinted_state/` and `/data/vinted_jobs/` lazily.

## One-time storageState seed

First-run on a new Railway-IP login may trigger Vinted's "new device"
verification (email/captcha). To avoid that risk on the first job:

1. On a desktop with Chromium installed, run a one-shot seed script:

   ```python
   import asyncio
   from playwright.async_api import async_playwright

   async def main():
       async with async_playwright() as p:
           browser = await p.chromium.launch(headless=False)
           context = await browser.new_context(
               viewport={"width": 1280, "height": 800},
               locale="en-GB",
               timezone_id="Europe/London",
           )
           page = await context.new_page()
           await page.goto("https://www.vinted.co.uk/member/general/login")
           print("Manually log in, complete any verification, then press Enter.")
           input()
           await context.storage_state(path="storage_state.json")
           print("Saved storage_state.json")
           await browser.close()

   asyncio.run(main())
   ```

2. Upload the resulting `storage_state.json` to the Railway volume at
   `/data/vinted_state/storage_state.json` via Railway CLI or web shell.
   The worker will detect it on next run and skip the password login
   path.

## How a job runs

1. Backend `POST /api/v1/vinted/jobs` accepts the draft fields +
   photos, stages photos to `/data/vinted_jobs/{job_id}/photos/`,
   creates the row in `tony_vinted_jobs`.
2. Matthew triggers the worker (manually for v1):
   ```
   python -m vinted_worker.operator <job_id>
   ```
3. Worker opens browser, checks login, navigates to Sell form, uploads
   photos, fills title/description/category/brand/condition/price,
   takes screenshot, marks `waiting_for_matthew_publish`.
4. Worker creates a Pending Action via `pending_actions` table —
   chat picks this up and Tony tells Matthew "Filled. Open Vinted, tap
   Publish."
5. Matthew opens Vinted on his phone, reviews, taps Publish himself.
6. Matthew replies "published" or hits the
   `POST /api/v1/vinted/jobs/{id}/published` endpoint to mark
   `posted_confirmed_at`.

## Failure modes and how to handle them

- **Login challenged (captcha / email verify):** worker stops, marks
  `requires_human`. Matthew sorts the verification on his own device,
  optionally re-seeds storageState, then triggers a retry.
- **Field selector miss:** worker logs a skip event for that field,
  continues with the rest. Matthew fills the missing field manually
  during review.
- **Safety violation (URL/DOM looks published):** worker stops with
  `SAFETY_VIOLATION.png` screenshot and `error_type=safety_violation`.
  Investigate before allowing more jobs.
- **Vinted DOM change (selectors stale):** several fields skip; check
  `tony_vinted_job_events` for fill_* events with `ok=false`. Update
  selectors in `vinted_actions.py`.

## Out of scope (deferred)

- 2captcha or any CAPTCHA-solving service.
- Anti-bot evasion (proxy rotation, user-agent spoofing).
- Multiple Vinted accounts.
- Auto-retry loops.
- Listing edit, delete, or any non-create action.
- FCM push notifications.
- Android UI for triggering jobs (curl/API only for v1).
