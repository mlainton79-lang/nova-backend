"""
Capabilities v1.1 seed.

Upserts the current canonical list of Tony's capabilities into the
capabilities table. Status vocabulary preserved as active|not_built
to match existing downstream consumers (gap_detector, prompts/tony,
builder/status). Vocabulary cleanup is deferred to N1.2.

Run by router.py startup _inits list, after init_capabilities_table
and register_new_capabilities.
"""

from app.core.capabilities import upsert_capability


CAPABILITIES_V1 = [
    # Vinted parent (legacy row, refreshed)
    {
        "name": "vinted",
        "description": "Assisted Vinted listing workflow (parent capability).",
        "status": "active",
        "runner": "android_kotlin+backend_python",
        "risk_level": "medium",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Assisted Vinted workflow shipped: draft generation, review screen, recent drafts, clipboard/share bridge. Direct autonomous Vinted web posting is NOT built and is represented separately by vinted_playwright_operator. Last shipped Android commit 40f6dc0.",
    },
    # Vinted granular capabilities (shipped)
    {
        "name": "vinted_draft_create",
        "description": "Generate Vinted listing draft from photos via Tony.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Shipped. Backend processes photos, returns title/description/price/category/condition draft.",
    },
    {
        "name": "vinted_draft_review",
        "description": "Review and edit Vinted draft before action.",
        "status": "active",
        "runner": "android_kotlin",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Shipped in Stage 2d (Android commit b88614c). Review screen with editable fields, copy buttons, retry/discard/mark-posted actions.",
    },
    {
        "name": "vinted_drafts_list",
        "description": "List recent Vinted drafts persisted across sessions.",
        "status": "active",
        "runner": "android_kotlin",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Shipped in Stage 2e-A (Android commits 0c4b773, 39d5c35). Drafts persist to filesDir/vinted_drafts/, accessible via drawer button or chat command.",
    },
    {
        "name": "vinted_open_helper",
        "description": "Share Vinted draft photos and text via Android share sheet.",
        "status": "active",
        "runner": "android_kotlin",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Shipped in Stage 2e-B (Android commit 40f6dc0). Bridge only: ACTION_SEND_MULTIPLE with photos + EXTRA_TEXT + clipboard fallback. NOTE: Vinted does NOT appear as share target on tested device — clipboard fallback is the actual usable path.",
    },
    {
        "name": "vinted_playwright_operator",
        "description": "Autonomous Vinted web listing via Playwright browser worker.",
        "status": "not_built",
        "runner": "playwright_worker",
        "risk_level": "critical",
        "approval_required": True,
        "cost_type": "platform_fee",
        "notes": "PLANNED. Phase 3A architecture comparison complete (Hetzner VPS recommended, deferred until budget allows). First milestone: fill-and-stop-at-submit-screen with Matthew approval gate. NEVER auto-post.",
    },
    # Email/Calendar (shipped)
    {
        "name": "gmail_read_multi_account",
        "description": "Read Gmail across multiple connected accounts.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "endpoint": "/api/v1/gmail/emails",
        "notes": "Shipped. 4 accounts connected via OAuth. Search, thread reconstruction, attachment parsing.",
    },
    {
        "name": "gmail_morning_summary",
        "description": "Daily morning summary of unread emails across accounts.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "endpoint": "/api/v1/gmail/morning",
        "notes": "Shipped. Returns unread count and per-account breakdown.",
    },
    {
        "name": "calendar_read_write",
        "description": "Read schedule and create calendar events.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "medium",
        "approval_required": False,
        "cost_type": "free",
        "endpoint": "/api/v1/calendar/today",
        "notes": "Shipped. Reuses Gmail OAuth tokens with calendar scope. Tony reads schedule, creates events.",
    },
    {
        "name": "proactive_alerts",
        "description": "Periodic scan for urgent items requiring attention.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "endpoint": "/api/v1/alerts",
        "notes": "Shipped. 48-hour scans, priority-ranked, surfaces email/calendar/case alerts without being asked.",
    },
    # Memory/vision/reading (shipped, with notes)
    {
        "name": "memory_system",
        "description": "Persistent memory across conversations.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "medium",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Shipped (instant memory, episodic, semantic, consolidator). KNOWN ISSUE: silent memory failures bug. Reliability sprint planned.",
    },
    {
        "name": "camera_vision_claude",
        "description": "Camera image analysis (Claude vision only).",
        "status": "active",
        "runner": "android_kotlin+backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "metered",
        "notes": "Shipped. Claude vision works. KNOWN ISSUE: OpenAI/Gemini vision broken (model string + image dispatch bugs).",
    },
    {
        "name": "file_reading",
        "description": "Read uploaded PDF/Word/TXT/JSON/CSV/Excel files.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "notes": "Shipped. Multiple format support via document_reader.",
    },
    # Code editing (shipped + planned)
    {
        "name": "code_edit_python_backend",
        "description": "Tony autonomously edits backend Python code, pushes to GitHub, Railway redeploys.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "high",
        "approval_required": True,
        "cost_type": "free",
        "notes": "Shipped. Push markers via auto_push.py, code_verify.py for programmatic verification. Approval should be enforced at the request level once approval gate ships (N2).",
    },
    {
        "name": "code_edit_kotlin_frontend",
        "description": "Tony autonomously edits Android Kotlin code.",
        "status": "not_built",
        "runner": "manual",
        "risk_level": "high",
        "approval_required": True,
        "cost_type": "free",
        "notes": "PLANNED. Currently Matthew handles all Kotlin edits via AIDE. Future: extend Tony's auto_push pattern to Android repo.",
    },
    # capability_builder (shipped but flagged)
    {
        "name": "capability_builder_self_expansion",
        "description": "Tony researches missing capabilities, writes code, pushes via GitHub.",
        "status": "not_built",
        "runner": "backend_python",
        "risk_level": "critical",
        "approval_required": True,
        "cost_type": "metered",
        "notes": "Code present at app/core/capability_builder.py (641 lines) but safety audit required before activation. Researches via Brave + Gemini, writes code, pushes via GitHub API. NEEDS APPROVAL GATE before this should be marked active. Audit phase planned (N1.5 or N2-pre).",
    },
    # Future capabilities
    {
        "name": "image_editing",
        "description": "Resize, crop, compress, brighten, sharpen images locally.",
        "status": "not_built",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "free",
        "notes": "PLANNED. Free/local via Pillow. Foundation for Vinted product photo prep, social media content.",
    },
    {
        "name": "video_creation",
        "description": "Assemble videos from images/clips with captions, music, voiceover.",
        "status": "not_built",
        "runner": "backend_python",
        "risk_level": "medium",
        "approval_required": False,
        "cost_type": "metered",
        "notes": "PLANNED. Free/local via FFmpeg. Future: TikTok/YouTube Shorts/Vinted item videos.",
    },
    {
        "name": "youtube_monitoring",
        "description": "Monitor YouTube channels and surface relevant new content.",
        "status": "not_built",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "cost_type": "metered",
        "notes": "PLANNED. YouTube Data API free tier (10k requests/day).",
    },
    {
        "name": "self_improvement_loop",
        "description": "Scheduled self-review where Tony identifies issues and proposes fixes.",
        "status": "not_built",
        "runner": "backend_python",
        "risk_level": "high",
        "approval_required": True,
        "cost_type": "metered",
        "notes": "PLANNED. Bounded self-improvement: Tony reviews himself periodically, proposes fixes, requires Matthew approval before any push. Builds on capability_builder.py once safety-audited.",
    },
]


def run_once():
    """Upsert all v1.1 capabilities. Called once at startup by router.py."""
    try:
        for cap in CAPABILITIES_V1:
            upsert_capability(**cap)
        print(f"[CAPABILITIES_V1] Seeded {len(CAPABILITIES_V1)} capabilities")
    except Exception as e:
        print(f"[CAPABILITIES_V1] Seed failed: {e}")
