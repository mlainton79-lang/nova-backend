"""
Vinted operator main entry — async Playwright orchestration.

Runs once per invocation with a job_id from CLI arg or VINTED_JOB_ID env.
Reads the job + draft fields from tony_vinted_jobs, opens a Chromium
browser context (storageState if seeded), logs in if needed, navigates
to the Sell form, fills every available field, takes a screenshot of
the filled state, and STOPS. Marks status=waiting_for_matthew_publish
and creates a Pending Action so Matthew sees the prompt to review +
publish manually.

NEVER clicks Publish. See safety.py.
"""
import asyncio
import os
import sys
import json
import traceback
from typing import Dict, Any

from playwright.async_api import async_playwright

from . import config, login, state_check, vinted_actions, safety


def _import_backend():
    """Defer backend imports — the worker container has /app on path."""
    sys.path.insert(0, "/app")
    from app.core import vinted_jobs  # noqa: E402
    from app.core import pending_actions  # noqa: E402
    return vinted_jobs, pending_actions


async def run_job(job_id: int) -> int:
    """
    Execute a single Vinted fill-and-stop job.
    Returns process exit code: 0 on success (incl. requires_human handover),
    non-zero on hard failure.
    """
    vinted_jobs, pending_actions = _import_backend()

    job = vinted_jobs.get_job(job_id)
    if not job:
        print(f"[VINTED_WORKER] job {job_id} not found", file=sys.stderr)
        return 2

    metadata: Dict[str, Any] = job.get("metadata") or {}
    item_name = job.get("item_name") or "untitled"

    vinted_jobs.update_status(job_id, "starting_browser", started=True)
    vinted_jobs.append_event(job_id, "browser_launching", "spinning up Chromium")

    photos_dir = config.photo_dir_for_job(job_id)
    screenshots_dir = config.screenshot_dir_for_job(job_id)
    config.ensure_dirs(photos_dir, screenshots_dir)

    photo_paths = []
    if os.path.isdir(photos_dir):
        for fn in sorted(os.listdir(photos_dir)):
            full = os.path.join(photos_dir, fn)
            if os.path.isfile(full):
                photo_paths.append(full)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.BROWSER_HEADLESS)
        context = None
        try:
            ctx_kwargs = dict(
                viewport={"width": config.VIEWPORT_WIDTH, "height": config.VIEWPORT_HEIGHT},
                locale=config.LOCALE,
                timezone_id=config.TIMEZONE_ID,
            )
            if os.path.exists(config.STORAGE_STATE_PATH):
                ctx_kwargs["storage_state"] = config.STORAGE_STATE_PATH
                vinted_jobs.append_event(job_id, "storage_state_loaded",
                                         "using existing storage_state.json")
            else:
                vinted_jobs.append_event(job_id, "storage_state_absent",
                                         "no storage_state.json — fresh context")

            context = await browser.new_context(**ctx_kwargs)
            context.set_default_timeout(config.DEFAULT_TIMEOUT_MS)
            page = await context.new_page()

            # ── Step 1: login state ────────────────────────────────────────
            vinted_jobs.update_status(job_id, "checking_login")
            logged_in = await state_check.is_logged_in(page)
            vinted_jobs.append_event(
                job_id, "login_state_checked",
                f"logged_in={logged_in}",
            )

            if not logged_in:
                if not config.has_login_credentials():
                    vinted_jobs.mark_requires_human(
                        job_id,
                        reason="not logged in and no credentials seeded — refresh storageState manually",
                    )
                    pending_actions.create_pending_action(
                        action_type="vinted_login_required",
                        original_query=f"vinted job {job_id}",
                        candidates=[{"job_id": job_id, "item_name": item_name}],
                        instruction="Refresh storage_state.json on the Railway volume, then reply 'retry' to resume.",
                    )
                    return 0

                vinted_jobs.update_status(job_id, "logging_in")
                vinted_jobs.append_event(job_id, "login_attempt_starting",
                                         "password flow")
                login_result = await login.attempt_password_login(
                    page,
                    config.get_login_email(),
                    config.get_login_password(),
                )
                vinted_jobs.append_event(
                    job_id, "login_result",
                    f"success={login_result.success} reason={login_result.reason}",
                )
                if not login_result.success:
                    if login_result.requires_human:
                        try:
                            ss_path = os.path.join(screenshots_dir, "login_blocked.png")
                            await page.screenshot(path=ss_path, full_page=True)
                            vinted_jobs.append_event(job_id, "screenshot_taken", ss_path)
                        except Exception:
                            pass
                        vinted_jobs.mark_requires_human(
                            job_id,
                            reason=f"login challenged: {login_result.reason}",
                        )
                        pending_actions.create_pending_action(
                            action_type="vinted_login_required",
                            original_query=f"vinted job {job_id}",
                            candidates=[{"job_id": job_id, "item_name": item_name}],
                            instruction="Vinted wants verification. Sort it on your phone, then reply 'retry'.",
                        )
                        return 0
                    vinted_jobs.update_status(
                        job_id, "error",
                        error_message=f"login failed: {login_result.reason}",
                        error_type="login_failure",
                    )
                    return 1

                # Persist refreshed storageState for next run.
                saved = await login.save_storage_state(context)
                vinted_jobs.append_event(
                    job_id, "storage_state_saved",
                    f"ok={saved} path={config.STORAGE_STATE_PATH}",
                )

            # ── Step 2: navigate to Sell form ──────────────────────────────
            vinted_jobs.update_status(job_id, "opening_sell_form")
            try:
                await page.goto(
                    config.VINTED_BASE_URL + config.VINTED_SELL_PATH,
                    wait_until="domcontentloaded",
                    timeout=config.DEFAULT_TIMEOUT_MS,
                )
            except Exception as e:
                vinted_jobs.update_status(
                    job_id, "error",
                    error_message=f"sell page navigation failed: {type(e).__name__}",
                    error_type="navigation_failure",
                )
                return 1

            # ── Step 3: upload photos ──────────────────────────────────────
            if photo_paths:
                vinted_jobs.update_status(job_id, "uploading_photos")
                ok, reason = await vinted_actions.upload_photos(page, photo_paths)
                vinted_jobs.append_event(job_id, "upload_photos",
                                         f"ok={ok} reason={reason}")
            else:
                vinted_jobs.append_event(job_id, "upload_photos_skipped",
                                         "no photos in job dir")

            # ── Step 4: fill fields ────────────────────────────────────────
            vinted_jobs.update_status(job_id, "filling_fields")

            field_results = {}
            field_results["title"] = await vinted_actions.fill_title(
                page, metadata.get("title", "") or item_name)
            field_results["description"] = await vinted_actions.fill_description(
                page, metadata.get("description", ""))
            field_results["category"] = await vinted_actions.select_category(
                page, metadata.get("category", ""))
            field_results["brand"] = await vinted_actions.select_brand(
                page, metadata.get("brand", ""))
            field_results["condition"] = await vinted_actions.select_condition(
                page, metadata.get("condition", ""))
            field_results["price"] = await vinted_actions.fill_price(
                page, metadata.get("price", ""))

            for fname, (ok, reason) in field_results.items():
                vinted_jobs.append_event(
                    job_id, f"fill_{fname}",
                    f"ok={ok} reason={reason}",
                )

            # Brief settle for client-side validation.
            await asyncio.sleep(2)

            # ── Step 5: SAFETY — verify no publish happened ────────────────
            is_safe, reason = await safety.verify_no_publish_async(page)
            vinted_jobs.append_event(
                job_id, "safety_verify_no_publish",
                f"is_safe={is_safe} reason={reason}",
            )
            if not is_safe:
                # Critical: take screenshot, mark error.
                try:
                    ss_path = os.path.join(screenshots_dir, "SAFETY_VIOLATION.png")
                    await page.screenshot(path=ss_path, full_page=True)
                    vinted_jobs.append_event(job_id, "screenshot_taken", ss_path)
                except Exception:
                    pass
                vinted_jobs.update_status(
                    job_id, "safety_violation",
                    error_message=f"verify_no_publish failed: {reason}",
                    error_type="safety_violation",
                )
                print(f"[VINTED_WORKER] CRITICAL: {reason}", file=sys.stderr)
                return 3

            # ── Step 6: screenshot the filled form ─────────────────────────
            ss_path = os.path.join(screenshots_dir, "filled.png")
            ok, reason = await vinted_actions.screenshot_pre_publish(page, ss_path)
            vinted_jobs.append_event(job_id, "screenshot_filled",
                                     f"ok={ok} reason={reason}")
            if ok:
                vinted_jobs.update_status(
                    job_id, "waiting_for_matthew_publish",
                    final_screenshot_path=ss_path,
                )
            else:
                vinted_jobs.update_status(
                    job_id, "waiting_for_matthew_publish",
                )

            # ── Step 7: surface a Pending Action so chat picks it up ───────
            pending_actions.create_pending_action(
                action_type="vinted_publish_pending",
                original_query=f"vinted job {job_id}",
                candidates=[{
                    "job_id": job_id,
                    "item_name": item_name,
                    "screenshot_path": ss_path if ok else None,
                }],
                instruction=(
                    f"Filled the listing for {item_name}. Open Vinted, "
                    f"check it, tap Publish."
                ),
            )

            return 0

        except safety.SafetyError as se:
            # A click was about to publish — this should never happen under
            # normal flow, but if a future selector change tripped a forbidden
            # button text, we want it loud.
            print(f"[VINTED_WORKER] SAFETY ERROR: {se}", file=sys.stderr)
            try:
                ss_path = os.path.join(screenshots_dir, "SAFETY_REFUSED.png")
                if context is not None:
                    pages = context.pages
                    if pages:
                        await pages[0].screenshot(path=ss_path, full_page=True)
                        vinted_jobs.append_event(job_id, "screenshot_taken", ss_path)
            except Exception:
                pass
            vinted_jobs.update_status(
                job_id, "safety_violation",
                error_message=str(se),
                error_type="safety_refused_click",
            )
            return 3

        except Exception as e:
            tb = traceback.format_exc()[:1000]
            vinted_jobs.update_status(
                job_id, "error",
                error_message=f"{type(e).__name__}: {str(e)[:200]}",
                error_type="unexpected_exception",
            )
            vinted_jobs.append_event(job_id, "exception", tb)
            return 1

        finally:
            try:
                if context is not None:
                    await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass


def _resolve_job_id() -> int:
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            sys.exit(f"invalid job_id arg: {sys.argv[1]}")
    env_val = os.environ.get("VINTED_JOB_ID")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            sys.exit(f"invalid VINTED_JOB_ID env: {env_val}")
    sys.exit("usage: python -m vinted_worker.operator <job_id>  (or set VINTED_JOB_ID)")


if __name__ == "__main__":
    job_id = _resolve_job_id()
    errors = config.validate_required()
    if errors:
        print(f"[VINTED_WORKER] config errors: {errors}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(run_job(job_id)))
