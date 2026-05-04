"""
Vinted password login + storageState save/load.

The login click is the ONLY submit-shaped click the worker performs. It
is annotated explicitly here as safe: logging in is not publishing. The
safety rail in safety.py does not list "log in" as a forbidden text —
it lists publish/post/upload patterns only.

If Vinted serves a captcha, email-verification challenge, or any
"unusual activity" intercept after the login click, this module returns
a CaptchaRequired / VerificationRequired result. Worker stops and asks
Matthew to handle it manually.

CRED DISCIPLINE:
- VINTED_EMAIL and VINTED_PASSWORD are read from os.environ via
  config.get_login_email() / config.get_login_password().
- These values are NEVER logged. Exceptions raised here include only
  the failure mode label, never the credentials.
- storageState write goes to config.STORAGE_STATE_PATH on the Railway
  volume. Path is gitignored. Contents are NEVER printed.
"""
import os
from . import config


class LoginResult:
    """Plain return type. No exceptions raised on auth failure — caller decides."""
    def __init__(self, success: bool, reason: str, requires_human: bool = False):
        self.success = success
        self.reason = reason            # short label, safe to log
        self.requires_human = requires_human


# Selectors for the Vinted login form. Multi-strategy with fallback —
# Vinted's DOM occasionally rotates names/data-testids.
EMAIL_INPUT_SELECTORS = [
    'input[name="email"]',
    'input[type="email"]',
    '[data-testid="login-email-input"]',
]

PASSWORD_INPUT_SELECTORS = [
    'input[name="password"]',
    'input[type="password"]',
    '[data-testid="login-password-input"]',
]

# Login submit selectors. Note: although this is a submit button, it is
# explicitly NOT in safety.PUBLISH_FORBIDDEN_TEXTS — login != publish.
LOGIN_SUBMIT_SELECTORS = [
    '[data-testid="login-submit-button"]',
    'button[type="submit"]:has-text("Log in")',
    'button:has-text("Log in")',
    'button:has-text("Sign in")',
]


# Selectors that indicate a verification/captcha challenge was shown
# AFTER login submit. If any present, worker stops and asks Matthew.
CHALLENGE_SELECTORS = [
    'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'div:has-text("Verify it\'s you")',
    'div:has-text("unusual activity")',
    'div:has-text("Enter the code")',
    '[data-testid="device-confirmation"]',
]


async def attempt_password_login(page, email: str, password: str) -> LoginResult:
    """
    Attempt a password-flow login on the Vinted login page.

    Caller passes credentials directly (read from config). Strings are
    typed into the form via Playwright's .fill() — never echoed or
    logged.

    Returns a LoginResult. Caller is responsible for follow-up: save
    storageState on success, mark requires_human on challenge, retry
    or escalate on failure.
    """
    if not email or not password:
        return LoginResult(False, "missing credentials", requires_human=True)

    # Navigate to the login page.
    try:
        await page.goto(
            config.VINTED_BASE_URL + config.VINTED_LOGIN_PATH,
            wait_until="domcontentloaded",
            timeout=config.DEFAULT_TIMEOUT_MS,
        )
    except Exception as e:
        return LoginResult(False, f"login page navigation failed: {type(e).__name__}")

    # Fill email.
    email_filled = False
    for sel in EMAIL_INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.fill(email)
                email_filled = True
                break
        except Exception:
            continue
    if not email_filled:
        return LoginResult(False, "email input not found", requires_human=True)

    # Fill password.
    password_filled = False
    for sel in PASSWORD_INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.fill(password)
                password_filled = True
                break
        except Exception:
            continue
    if not password_filled:
        return LoginResult(False, "password input not found", requires_human=True)

    # Click the login submit. SAFE: this is the login form, not the
    # listing form. safety.PUBLISH_FORBIDDEN_TEXTS does not match these
    # button labels. Login is not publish.
    submit_clicked = False
    for sel in LOGIN_SUBMIT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.click()
                submit_clicked = True
                break
        except Exception:
            continue
    if not submit_clicked:
        return LoginResult(False, "login submit not found", requires_human=True)

    # Wait for either redirect or challenge. Bounded total wait.
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    # Detect challenge (captcha, email verification, device confirmation).
    for sel in CHALLENGE_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                return LoginResult(
                    False,
                    "verification challenge presented",
                    requires_human=True,
                )
        except Exception:
            continue

    # Quick re-check that we're now in a logged-in state. Caller can
    # do a richer state_check.is_logged_in() afterwards too.
    current_url = page.url
    if "/login" in current_url:
        return LoginResult(False, "still on login page after submit")

    return LoginResult(True, "login submit accepted")


async def save_storage_state(context, path: str = None) -> bool:
    """
    Persist cookies + localStorage to the Railway volume.

    NEVER print path contents. Path itself is allowed in event log
    (it's a directory location, not a secret).
    """
    target = path or config.STORAGE_STATE_PATH
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        await context.storage_state(path=target)
        return True
    except Exception:
        return False
