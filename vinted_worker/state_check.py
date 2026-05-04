"""
Login-state check for the Vinted worker.

Pure read operations. No clicks, no submissions. Navigates to the member
page and inspects the DOM to determine whether the current Playwright
context is logged in.

If is_logged_in() returns False, operator.py decides whether to attempt
a password login (only if VINTED_EMAIL + VINTED_PASSWORD are set) or
mark the job requires_human (asking Matthew to refresh the storageState
seed manually).
"""
from . import config


# DOM signals indicating a logged-in session. Vinted's member page
# renders an avatar, "My account" / "Profile" links, and a logout
# control when authenticated. If any of these is present, treat the
# session as live.
LOGGED_IN_SELECTORS = [
    '[data-testid="header-avatar"]',
    '[data-testid="user-menu-button"]',
    'a[href*="/member/general/logout"]',
    'a[href*="/member/general/personalisation"]',
    'button:has-text("Log out")',
]


# DOM signals indicating a login form is visible (i.e. not logged in).
LOGIN_FORM_SELECTORS = [
    'input[name="email"]',
    'input[type="email"]',
    'input[name="password"]',
    'button:has-text("Continue with email")',
]


async def is_logged_in(page, timeout_ms: int = 10000) -> bool:
    """
    Navigate to the member page and detect login state.

    Returns True if any logged-in signal is present.
    Returns False if a login form is visible OR no signal could be
    determined (treated as not-logged-in for safety — caller will decide
    whether to attempt login).

    No clicks, no form submissions performed here.
    """
    try:
        await page.goto(
            config.VINTED_BASE_URL + config.VINTED_MEMBER_PATH,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
    except Exception:
        return False

    # Quick check for logged-in signals.
    for sel in LOGGED_IN_SELECTORS:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                return True
        except Exception:
            continue

    # Quick check for login-form signals — proves we're not logged in.
    for sel in LOGIN_FORM_SELECTORS:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                return False
        except Exception:
            continue

    # Indeterminate — treat as not-logged-in for safety.
    return False
