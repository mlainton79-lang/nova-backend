"""
Safety rails for the Vinted operator worker.

The worker fills the Sell form and STOPS. It must never click any button
that would publicly submit the listing. Matthew is the only entity that
publishes — by tapping Publish in his own Vinted client.

Two layers of defence:

1. assert_safe_to_proceed(action, target_text):
   Called BEFORE every click in vinted_actions. Raises SafetyError if the
   click target text matches a publish-shaped pattern. This makes it
   structurally impossible to ship a code path that publishes — any edit
   that adds such a click crashes at runtime, loud.

2. verify_no_publish(page):
   Called AT THE END of the fill flow. Inspects current URL and DOM for
   evidence the listing was submitted (URL changed to /items/{id},
   "Item posted" banner, etc). If matched, the worker logs CRITICAL and
   marks the job as a safety violation — Matthew investigates.

NEVER weaken these checks. NEVER add an exception for a "we know what
we're doing" path. The day this worker autonomously publishes is the day
trust collapses.
"""
import re
from typing import Tuple


class SafetyError(Exception):
    """Raised when the worker is about to do something that could publish."""
    pass


# Click target text patterns that indicate a publish-shaped action.
# Match is case-insensitive substring. Login buttons are explicitly NOT
# in this list — login is a different submit (and is the only "submit-
# shaped" click the worker performs, annotated as safe in login.py).
PUBLISH_FORBIDDEN_TEXTS = [
    "publish",
    "post item",
    "list item",
    "submit listing",
    "upload item",
    "upload listing",
    "list now",
    "post now",
]


# URL patterns that indicate a listing was already published.
# Vinted typically redirects to /items/{numeric_id} or /catalog/... on
# successful submission. Keep this conservative — false positives here
# only cost a screenshot + manual investigation, false negatives lose
# trust.
PUBLISHED_URL_PATTERNS = [
    r"/items/\d+(?:[/?#]|$)",
    r"/wardrobe/",
    r"/catalog/.*?\?recently_added=",
]


# DOM text that indicates the listing was just posted. Localised English
# strings. If Vinted's UI ever changes language, expand this set.
PUBLISHED_DOM_TEXTS = [
    "Item listed",
    "Listed!",
    "Item posted",
    "Successfully posted",
    "Your item is live",
    "Item is now visible",
]


def assert_safe_to_proceed(action: str, target_text: str) -> None:
    """
    Refuse a click whose target text looks like a publish action.

    `action` is a short label for the operation (e.g. "select_category",
    "fill_title") used only in the exception message — useful for
    debugging which step tripped the rail. `target_text` is the visible
    text of the element about to be clicked.

    Raises SafetyError on any forbidden-pattern hit. Worker callers must
    NOT catch SafetyError — it should propagate, fail the job, and log
    the violation. Catching it would defeat the rail.
    """
    if not target_text:
        return
    lowered = target_text.lower()
    for forbidden in PUBLISH_FORBIDDEN_TEXTS:
        if forbidden in lowered:
            raise SafetyError(
                f"REFUSED: '{action}' would click '{target_text}' which "
                f"matches forbidden pattern '{forbidden}'. Worker must "
                f"never publish. If this fired on a legitimate non-publish "
                f"control, the selector or target_text is wrong — fix the "
                f"caller, never widen the safety list."
            )


def verify_no_publish(page) -> Tuple[bool, str]:
    """
    Inspect the current page for evidence of a publish having happened.

    Returns (is_safe, reason).
      is_safe=True  — pre-publish state confirmed; reason is a short
                       affirmation suitable for an event log.
      is_safe=False — possible/actual publish detected. Caller MUST
                       mark the job as a safety violation, screenshot,
                       and stop.

    Use sync Playwright calls — caller passes a sync Page or wraps in a
    sync context. (operator.py uses async — see the async wrapper
    verify_no_publish_async below.)
    """
    try:
        url = page.url
    except Exception as e:
        return False, f"could not read page URL: {e}"

    for pattern in PUBLISHED_URL_PATTERNS:
        if re.search(pattern, url):
            return False, f"URL matches published pattern '{pattern}': {url}"

    for text in PUBLISHED_DOM_TEXTS:
        try:
            if page.locator(f"text={text}").count() > 0:
                return False, f"DOM contains posted indicator: '{text}'"
        except Exception:
            # If locator probe fails, fall through — don't false-fail.
            continue

    return True, "pre-publish state confirmed"


async def verify_no_publish_async(page) -> Tuple[bool, str]:
    """Async variant for Playwright async API used by operator.py."""
    try:
        url = page.url
    except Exception as e:
        return False, f"could not read page URL: {e}"

    for pattern in PUBLISHED_URL_PATTERNS:
        if re.search(pattern, url):
            return False, f"URL matches published pattern '{pattern}': {url}"

    for text in PUBLISHED_DOM_TEXTS:
        try:
            count = await page.locator(f"text={text}").count()
            if count > 0:
                return False, f"DOM contains posted indicator: '{text}'"
        except Exception:
            continue

    return True, "pre-publish state confirmed"
