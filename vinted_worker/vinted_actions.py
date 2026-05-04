"""
Vinted Sell-form actions — selector library + fill helpers.

Each action wraps Vinted DOM interaction with multi-strategy selectors
(data-testid, name, placeholder, label) and a graceful-fallback policy:
if all selectors miss for a field, the action logs a skip event and
returns False — operator.py continues with the rest of the form, and
Matthew fills the missing field manually when reviewing.

EVERY action that performs a click passes the click target text through
safety.assert_safe_to_proceed() first. This is the structural rail
that makes a publish click impossible — see safety.py.

NEVER add a function that clicks Publish/Upload-item/Post-item.
"""
import asyncio
from typing import List, Optional, Tuple

from . import safety


# ── Photo upload ────────────────────────────────────────────────────────────

PHOTO_INPUT_SELECTORS = [
    'input[type="file"][accept*="image"]',
    'input[type="file"]',
    '[data-testid="photo-upload-input"]',
]


async def upload_photos(page, photo_paths: List[str]) -> Tuple[bool, str]:
    """
    Attach photo files to the Vinted Sell form's hidden file input.

    Uses Playwright's set_input_files which writes directly to the
    <input type=file> element — no clicks required, so no safety
    rail interaction needed. (Even if it did, "upload" without "item"
    is in PUBLISH_FORBIDDEN_TEXTS as "upload item" — set_input_files
    does not click any element, it just sets the file list.)

    Returns (ok, reason).
    """
    if not photo_paths:
        return False, "no photos provided"

    for sel in PHOTO_INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.set_input_files(photo_paths)
                # Best-effort wait for upload progress to complete. Vinted
                # shows thumbnails when uploads finish — wait briefly.
                await asyncio.sleep(3)
                return True, f"uploaded {len(photo_paths)} photo(s)"
        except Exception as e:
            continue

    return False, "photo input not found"


# ── Title ────────────────────────────────────────────────────────────────────

TITLE_INPUT_SELECTORS = [
    '[data-testid="title-input"] input',
    'input[name="title"]',
    'input[placeholder*="Title" i]',
    'input[aria-label*="title" i]',
]


async def fill_title(page, title: str) -> Tuple[bool, str]:
    """Vinted enforces a 60-char title limit; truncate to be safe."""
    if not title:
        return False, "empty title"
    safe_title = title[:60].strip()

    for sel in TITLE_INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.fill(safe_title)
                return True, f"filled title ({len(safe_title)} chars)"
        except Exception:
            continue
    return False, "title input not found"


# ── Description ──────────────────────────────────────────────────────────────

DESCRIPTION_INPUT_SELECTORS = [
    '[data-testid="description-input"] textarea',
    'textarea[name="description"]',
    'textarea[placeholder*="Description" i]',
    'textarea[aria-label*="description" i]',
]


async def fill_description(page, description: str) -> Tuple[bool, str]:
    """Vinted description limit is 1500 chars; truncate to be safe."""
    if not description:
        return False, "empty description"
    safe_desc = description[:1500].strip()

    for sel in DESCRIPTION_INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.fill(safe_desc)
                return True, f"filled description ({len(safe_desc)} chars)"
        except Exception:
            continue
    return False, "description input not found"


# ── Category dropdown ────────────────────────────────────────────────────────

CATEGORY_OPENER_SELECTORS = [
    '[data-testid="catalog-select-input"]',
    'button:has-text("Category")',
    'div:has-text("Category") button',
]


async def select_category(page, category_string: str) -> Tuple[bool, str]:
    """
    Best-effort. Opens the category picker, navigates to a leaf matching
    the supplied string. If no clean match, leaves blank — Matthew sets
    it manually when reviewing.

    Each click target is checked through safety.assert_safe_to_proceed.
    """
    if not category_string:
        return False, "no category string"

    opener_clicked = False
    for sel in CATEGORY_OPENER_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await page.locator(sel).count() == 0:
                continue
            target_text = (await loc.inner_text()) if await loc.count() > 0 else "category opener"
            safety.assert_safe_to_proceed("select_category:opener", target_text)
            await loc.click()
            opener_clicked = True
            break
        except safety.SafetyError:
            raise  # propagate — never swallow safety errors
        except Exception:
            continue
    if not opener_clicked:
        return False, "category dropdown opener not found"

    # Type to search within the picker.
    await asyncio.sleep(0.5)
    try:
        search_input = page.locator('input[placeholder*="Search" i]').first
        if await search_input.count() > 0:
            await search_input.fill(category_string)
            await asyncio.sleep(0.5)
    except Exception:
        pass

    # Pick first matching option. Multi-strategy.
    candidate_selectors = [
        f'button:has-text("{category_string}")',
        f'li:has-text("{category_string}")',
        f'[role="option"]:has-text("{category_string}")',
    ]
    for sel in candidate_selectors:
        try:
            loc = page.locator(sel).first
            if await page.locator(sel).count() == 0:
                continue
            target_text = (await loc.inner_text()) if await loc.count() > 0 else category_string
            safety.assert_safe_to_proceed("select_category:option", target_text)
            await loc.click()
            return True, f"selected category '{category_string}'"
        except safety.SafetyError:
            raise
        except Exception:
            continue

    return False, f"no category option matched '{category_string}'"


# ── Brand ────────────────────────────────────────────────────────────────────

BRAND_OPENER_SELECTORS = [
    '[data-testid="brand-select-input"]',
    'button:has-text("Brand")',
    'div:has-text("Brand") button',
]


async def select_brand(page, brand_string: str) -> Tuple[bool, str]:
    if not brand_string:
        return False, "no brand string"

    opened = False
    for sel in BRAND_OPENER_SELECTORS:
        try:
            if await page.locator(sel).count() == 0:
                continue
            loc = page.locator(sel).first
            target_text = (await loc.inner_text()) if await loc.count() > 0 else "brand opener"
            safety.assert_safe_to_proceed("select_brand:opener", target_text)
            await loc.click()
            opened = True
            break
        except safety.SafetyError:
            raise
        except Exception:
            continue
    if not opened:
        return False, "brand dropdown opener not found"

    await asyncio.sleep(0.5)

    # Type the brand into the search box.
    try:
        search_input = page.locator('input[placeholder*="Brand" i], input[placeholder*="Search" i]').first
        if await search_input.count() > 0:
            await search_input.fill(brand_string)
            await asyncio.sleep(1)  # wait for suggestions
    except Exception:
        pass

    # Click first suggestion matching brand_string.
    candidate_selectors = [
        f'li:has-text("{brand_string}")',
        f'button:has-text("{brand_string}")',
        f'[role="option"]:has-text("{brand_string}")',
    ]
    for sel in candidate_selectors:
        try:
            if await page.locator(sel).count() == 0:
                continue
            loc = page.locator(sel).first
            target_text = (await loc.inner_text()) if await loc.count() > 0 else brand_string
            safety.assert_safe_to_proceed("select_brand:option", target_text)
            await loc.click()
            return True, f"selected brand '{brand_string}'"
        except safety.SafetyError:
            raise
        except Exception:
            continue

    return False, f"no brand option matched '{brand_string}'"


# ── Condition ────────────────────────────────────────────────────────────────

CONDITION_OPENER_SELECTORS = [
    '[data-testid="condition-select-input"]',
    'button:has-text("Condition")',
    'div:has-text("Condition") button',
]


async def select_condition(page, condition_string: str) -> Tuple[bool, str]:
    if not condition_string:
        return False, "no condition string"

    opened = False
    for sel in CONDITION_OPENER_SELECTORS:
        try:
            if await page.locator(sel).count() == 0:
                continue
            loc = page.locator(sel).first
            target_text = (await loc.inner_text()) if await loc.count() > 0 else "condition opener"
            safety.assert_safe_to_proceed("select_condition:opener", target_text)
            await loc.click()
            opened = True
            break
        except safety.SafetyError:
            raise
        except Exception:
            continue
    if not opened:
        return False, "condition dropdown opener not found"

    await asyncio.sleep(0.5)

    candidate_selectors = [
        f'li:has-text("{condition_string}")',
        f'button:has-text("{condition_string}")',
        f'[role="option"]:has-text("{condition_string}")',
    ]
    for sel in candidate_selectors:
        try:
            if await page.locator(sel).count() == 0:
                continue
            loc = page.locator(sel).first
            target_text = (await loc.inner_text()) if await loc.count() > 0 else condition_string
            safety.assert_safe_to_proceed("select_condition:option", target_text)
            await loc.click()
            return True, f"selected condition '{condition_string}'"
        except safety.SafetyError:
            raise
        except Exception:
            continue

    return False, f"no condition option matched '{condition_string}'"


# ── Price ────────────────────────────────────────────────────────────────────

PRICE_INPUT_SELECTORS = [
    '[data-testid="price-input"] input',
    'input[name="price"]',
    'input[placeholder*="Price" i]',
    'input[aria-label*="price" i]',
]


async def fill_price(page, price_string: str) -> Tuple[bool, str]:
    if not price_string:
        return False, "no price"

    # Strip currency symbols, keep digits + decimal point.
    digits = "".join(c for c in str(price_string) if c.isdigit() or c == ".")
    if not digits:
        return False, "no numeric price after sanitisation"

    for sel in PRICE_INPUT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                await page.locator(sel).first.fill(digits)
                return True, f"filled price '{digits}'"
        except Exception:
            continue
    return False, "price input not found"


# ── Screenshot ──────────────────────────────────────────────────────────────

async def screenshot_pre_publish(page, path: str) -> Tuple[bool, str]:
    """Full-page screenshot for Matthew's review. No clicks."""
    try:
        await page.screenshot(path=path, full_page=True)
        return True, f"screenshot saved: {path}"
    except Exception as e:
        return False, f"screenshot failed: {type(e).__name__}"
