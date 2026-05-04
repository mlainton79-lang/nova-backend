"""
Vinted worker config — env vars, paths, validation.

CRED DISCIPLINE:
- VINTED_EMAIL and VINTED_PASSWORD live ONLY in Railway env vars.
- They are read here once and exposed via accessor functions.
- They are NEVER logged, NEVER printed, NEVER included in exception
  messages. If you need to confirm presence in diagnostics, use
  has_login_credentials() — which returns bool only.
- storageState path is on the Railway volume mount and never echoed.
"""
import os
from typing import Optional

# Railway volume mount root. Per Dockerfile.vinted_worker, /data is the
# mounted volume. Sub-directories are created lazily by the worker.
DATA_ROOT = os.environ.get("DATA_ROOT", "/data")

# Where storageState (cookies + localStorage after login) is persisted.
# Single-account, single file. NEVER cat or print contents.
STORAGE_STATE_DIR = os.environ.get("STORAGE_STATE_DIR", os.path.join(DATA_ROOT, "vinted_state"))
STORAGE_STATE_PATH = os.path.join(STORAGE_STATE_DIR, "storage_state.json")

# Where photos are staged per job by the backend; worker reads from here.
PHOTO_BASE = os.environ.get("PHOTO_BASE", os.path.join(DATA_ROOT, "vinted_jobs"))

# Database connection — same string as the web service.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Vinted-side config.
VINTED_BASE_URL = "https://www.vinted.co.uk"
VINTED_SELL_PATH = "/items/new"
VINTED_LOGIN_PATH = "/member/general/login"
VINTED_MEMBER_PATH = "/member"

# Browser config.
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() == "true"
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
LOCALE = "en-GB"
TIMEZONE_ID = "Europe/London"
DEFAULT_TIMEOUT_MS = 30000


def has_login_credentials() -> bool:
    """Bool only. Never returns the values themselves."""
    return bool(os.environ.get("VINTED_EMAIL")) and bool(os.environ.get("VINTED_PASSWORD"))


def get_login_email() -> Optional[str]:
    """Internal use only — caller must NEVER log the return value."""
    val = os.environ.get("VINTED_EMAIL")
    return val if val else None


def get_login_password() -> Optional[str]:
    """Internal use only — caller must NEVER log the return value."""
    val = os.environ.get("VINTED_PASSWORD")
    return val if val else None


def photo_dir_for_job(job_id: int) -> str:
    return os.path.join(PHOTO_BASE, str(job_id), "photos")


def screenshot_dir_for_job(job_id: int) -> str:
    return os.path.join(PHOTO_BASE, str(job_id), "screenshots")


def ensure_dirs(*paths: str) -> None:
    for p in paths:
        os.makedirs(p, exist_ok=True)


def validate_required() -> list:
    """Returns list of missing-required-config error strings (empty = ok)."""
    errors = []
    if not DATABASE_URL:
        errors.append("DATABASE_URL not set")
    if not os.path.isdir(DATA_ROOT):
        # Don't fail — worker may create on first use. Just note.
        pass
    return errors
