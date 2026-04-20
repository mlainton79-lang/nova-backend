"""
File extraction utilities.

Handles document types that the backend needs to decode beyond plain text:
- ZIP archives (extract text/code entries)
- Future: RAR, tar, etc.

Returns a tuple (extracted_text, failed_reason). Only one is non-null.
"""
import base64
import io
import zipfile
from typing import Tuple, Optional

# Which file extensions inside a ZIP we'll extract and show to Tony
TEXT_EXTENSIONS = {
    ".py", ".kt", ".kts", ".java", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".scss", ".xml", ".json", ".yaml", ".yml",
    ".toml", ".md", ".txt", ".sh", ".bash", ".sql", ".csv",
    ".gradle", ".properties", ".gitignore", ".dockerignore",
    ".cfg", ".ini", ".env", ".conf", ".go", ".rs", ".rb",
    ".c", ".cpp", ".h", ".hpp", ".swift", ".dart",
    "Dockerfile", "Makefile", "Procfile", "requirements.txt",
}

# Files to skip entirely
SKIP_PATTERNS = {
    "__MACOSX", ".DS_Store", "node_modules", ".git/",
    "build/", "dist/", ".gradle/", ".idea/", "__pycache__",
    "target/", ".venv/", "venv/", "env/",
}

# Binary extensions we never try to read as text
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".doc", ".xls", ".ppt", ".odt",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".exe", ".dll",
    ".so", ".dylib", ".class", ".jar", ".apk", ".aab",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".pyc", ".pyo",
}

MAX_ZIP_ENTRIES = 200
MAX_ZIP_TOTAL_BYTES = 10 * 1024 * 1024  # 10MB text total
MAX_FILE_BYTES = 500 * 1024  # 500KB per text file


def _should_extract(filename: str) -> bool:
    """Decide whether a file inside a ZIP should be extracted as text."""
    if any(p in filename for p in SKIP_PATTERNS):
        return False
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in BINARY_EXTENSIONS):
        return False
    if any(lower.endswith(ext) for ext in TEXT_EXTENSIONS):
        return True
    # Also match known filenames without extensions
    basename = filename.rsplit("/", 1)[-1]
    if basename in TEXT_EXTENSIONS:
        return True
    return False


def extract_zip_text(zip_base64: str, zip_name: str = "archive.zip") -> Tuple[Optional[str], Optional[str]]:
    """
    Extract text content from a base64-encoded ZIP archive.
    Returns (extracted_text, None) on success, or (None, reason) on failure.
    """
    try:
        raw = base64.b64decode(zip_base64)
        if len(raw) > 50 * 1024 * 1024:
            return None, f"ZIP too large ({len(raw)//1024//1024}MB — max 50MB)"

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            entries = zf.namelist()

            if len(entries) > MAX_ZIP_ENTRIES:
                return None, f"ZIP has {len(entries)} entries — max {MAX_ZIP_ENTRIES}. Extract and upload specific files instead."

            extractable = [n for n in entries if _should_extract(n) and not n.endswith("/")]
            skipped = len(entries) - len(extractable)

            if not extractable:
                return None, f"ZIP has {len(entries)} entries but none are readable text/code files."

            parts = [f"=== Contents of {zip_name} ({len(extractable)} files, {skipped} skipped) ==="]
            total_bytes = 0

            for entry in sorted(extractable):
                try:
                    info = zf.getinfo(entry)
                    if info.file_size > MAX_FILE_BYTES:
                        parts.append(f"\n--- {entry} ({info.file_size} bytes — too large, skipped) ---")
                        continue
                    with zf.open(entry) as f:
                        content_bytes = f.read()
                    # Try to decode as UTF-8 first, then latin-1 as fallback
                    try:
                        text = content_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            text = content_bytes.decode("latin-1")
                        except Exception:
                            parts.append(f"\n--- {entry} (binary or unreadable, skipped) ---")
                            continue

                    total_bytes += len(text)
                    if total_bytes > MAX_ZIP_TOTAL_BYTES:
                        parts.append(f"\n--- [truncated: total exceeded {MAX_ZIP_TOTAL_BYTES // (1024*1024)}MB] ---")
                        break

                    parts.append(f"\n\n--- {entry} ---\n{text}")
                except Exception as e:
                    parts.append(f"\n--- {entry} (read error: {e}) ---")

            return "\n".join(parts), None

    except zipfile.BadZipFile:
        return None, "File is not a valid ZIP archive."
    except Exception as e:
        return None, f"ZIP extraction failed: {e}"


def extract_if_zip(document_base64: Optional[str], document_mime: Optional[str],
                   document_name: Optional[str]) -> Optional[str]:
    """
    If the document is a ZIP, extract its text contents.
    Returns extracted text (with file boundaries marked) or None if not a ZIP.
    """
    if not document_base64:
        return None

    is_zip = (
        (document_mime and "zip" in document_mime.lower()) or
        (document_name and document_name.lower().endswith(".zip"))
    )

    if not is_zip:
        return None

    extracted, reason = extract_zip_text(document_base64, document_name or "archive.zip")
    if extracted:
        return extracted
    # Return an honest explanation that Tony can then surface
    return f"[ZIP file received: {document_name} — could not extract: {reason}]"
