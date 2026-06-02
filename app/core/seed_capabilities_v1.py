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
        "description": "Review a Vinted draft by id. Two surfaces: Android UI (editable review screen with copy/retry/discard) and backend (chain-aware programmatic read for planner steps that need to inspect a draft).",
        "status": "active",
        "runner": "android_kotlin+backend_python",
        "risk_level": "low",
        "approval_required": False,
        "external_effect": False,
        "cost_type": "free",
        "notes": "R2.4+ (2026-06-02): added backend dispatcher branch in plan_executor. Calls selling.drafts.get_draft(draft_id) and returns compact summary {title, description_chars, price, condition, image_count, status, warnings} for downstream chat/reason. Chain-aware: resolves draft_id from a prior vinted_drafts_list step's results. Android UI piece unchanged (Stage 2d, commit b88614c).",
    },
    {
        "name": "vinted_drafts_list",
        "description": "List recent Vinted drafts. Two surfaces: Android UI (drawer/chat command over filesDir persistence) and backend (chain-aware programmatic read over tony_drafts table for planner steps that need to enumerate then resolve a specific draft by description).",
        "status": "active",
        "runner": "android_kotlin+backend_python",
        "risk_level": "low",
        "approval_required": False,
        "external_effect": False,
        "cost_type": "free",
        "notes": "Original Stage 2e-A Android piece unchanged (commits 0c4b773, 39d5c35). R2.4+ (2026-06-02): added backend dispatcher branch in plan_executor. Calls selling.drafts.list_drafts(limit=20) and returns compact array of {id, title, status, approval_state, image_count, price, created_at} suitable for downstream vinted_draft_review chain-aware draft_id resolution.",
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
        # R2.4+ reason: gap-bridge reasoning capability. Registered to
        # satisfy planner-decomposed analysis steps (e.g. "find a free
        # 30-min slot tomorrow from the calendar_read results") that
        # would otherwise fall into `gap` because no underlying read or
        # write capability matches. Internal-only — no external effect,
        # no spending, no approval. Chain-aware by default (sees prior
        # step results via the prior_results plumbing).
        "name": "reason",
        "description": "Internal reasoning / analysis step. Takes prior step results plus the step description, returns structured concrete output the next step can consume. Use this for 'analyse', 'find', 'pick', 'decide' steps between concrete read and write capabilities.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "external_effect": False,
        "cost_type": "free",
        "notes": "R2.4+ (2026-06-02). Registered to bridge planner-decomposed analysis steps. Plan executor dispatcher uses gemini with a structured-analysis prompt frame and prior_results context.",
    },
    {
        # R2.4+ gmail_send: corrected metadata. The legacy capabilities row
        # backfilled into tony_capabilities defaulted to external_effect=
        # False / approval_required=False, which is unsafe — sending email
        # IS external_effect by definition. This upsert via the canonical
        # facade pushes external_effect=True, approval_required=True, and
        # risk_level=medium so the governor (R2.1b) correctly classifies
        # gmail_send as external_effect and default-denies without an
        # approval_token. The plan_executor dispatcher only fires after
        # the governor allows; it then runs LLM-based parameter extraction
        # with strict validation before calling gmail_service.send_email.
        "name": "gmail_send",
        "description": "Send emails from any connected Gmail account. Requires governor approval per call — external_effect.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "medium",
        "approval_required": True,
        "external_effect": True,
        "cost_type": "free",
        "endpoint": "/api/v1/gmail/send",
        "notes": "Metadata corrected R2.4+ (2026-06-01). Plan executor dispatcher requires approval_token; extracts {account,to,subject,body} via gemini_json, validates account is connected + to is a valid email + all fields non-empty before calling send_email.",
    },
    # R2.4+ calendar split: the legacy calendar_read_write lumped read AND
    # write under one capability_key with approval_required=False — which
    # meant the governor would let create_event fire without approval.
    # Split below into calendar_read (truly read-only) and calendar_write
    # (external_effect, gated). The lumped row is deprecated at the bottom
    # of run_once so the planner no longer sees it.
    {
        "name": "calendar_read",
        "description": "Read upcoming events / today's schedule from a connected Google Calendar (uses Gmail OAuth with calendar scope).",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "low",
        "approval_required": False,
        "external_effect": False,
        "cost_type": "free",
        "endpoint": "/api/v1/calendar/today",
        "notes": "R2.4+ — read-only half of the former calendar_read_write. Calls calendar_service.get_upcoming_events / get_todays_schedule.",
    },
    {
        "name": "calendar_write",
        "description": "Create a calendar event in a connected Google Calendar. Requires governor approval per call — external_effect.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "medium",
        "approval_required": True,
        "external_effect": True,
        "cost_type": "free",
        "endpoint": "/api/v1/calendar/today",
        "notes": "R2.4+ — write half of the former calendar_read_write. Governor default-denies without approval_token. Plan executor dispatcher extracts {account, title, start_iso, end_iso} via gemini_json, validates, then calls calendar_service.create_event.",
    },
    {
        # R2.4+ gmail_delete: destructive sibling of gmail_send. Uses
        # trash_email (move-to-Trash, 30-day Gmail retention) — REVERSIBLE
        # destructive, not permanent. v0 deliberately does NOT expose
        # delete_email (permanent). If permanent delete is ever needed it
        # becomes a separate capability with even stricter safety.
        # Governor default-denies absent approval_token; dispatcher does
        # verify-by-GET before trashing so the audit trail captures
        # exactly what was destroyed.
        "name": "gmail_delete",
        "description": "Move a Gmail message to Trash by message_id (REVERSIBLE — 30-day retention before permanent deletion). Destructive — requires governor approval per call. Chain-aware: resolves message_id from a prior gmail_read step's results.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "high",
        "approval_required": True,
        "external_effect": True,
        "cost_type": "free",
        "endpoint": "/api/v1/gmail/trash",
        "notes": "R2.4+ (2026-06-02). Governor default-denies. Dispatcher extracts {account, message_id} via gemini_json (disable_thinking=True), validates account is connected + message_id non-empty, fetches the message via get_email_body to confirm it exists, then calls trash_email (REVERSIBLE — moves to Trash, kept 30 days before permanent purge). Trace captures the message's from/subject/date so audits can see what was trashed.",
    },
    {
        # R2.4+ gmail_delete_permanent: PERMANENT, UNRECOVERABLE delete via
        # gmail_service.delete_email (DELETE /messages/{id} — no Trash
        # fallback, no 30-day grace period). One notch above gmail_delete:
        #   - risk_level=critical (vs gmail_delete's high)
        #   - additional kill-switch env var GMAIL_PERMANENT_DELETE_ENABLED
        #     (default false) — even with an approval_token, the dispatcher
        #     refuses unless that env var is explicitly on. Two-layer
        #     gating on this capability: token AND env var.
        # All the other safety beats from gmail_delete still apply:
        # match_evidence cross-check, verify-by-GET capturing the
        # destroyed message's metadata in the trace.
        "name": "gmail_delete_permanent",
        "description": "Permanently delete a Gmail message by message_id (IRREVERSIBLE — no Trash, no recovery). Requires governor approval per call AND GMAIL_PERMANENT_DELETE_ENABLED env var on. Prefer gmail_delete (reversible trash) unless permanent purge is genuinely required.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "critical",
        "approval_required": True,
        "external_effect": True,
        "cost_type": "free",
        "endpoint": "/api/v1/gmail/delete",
        "notes": "R2.4+ (2026-06-02). Two-layer safety: governor (approval_token) AND GMAIL_PERMANENT_DELETE_ENABLED env var (default false). Then standard match-evidence cross-check + verify-by-GET. Calls gmail_service.delete_email (HTTP DELETE — no recovery). Trace captures the message's from/subject/date and marks permanent=True so audits can distinguish from gmail_delete's reversible trash.",
    },
    {
        # R2.4+ calendar_delete: destructive, external_effect, governor
        # default-denies. Same three-layer safety as calendar_write PLUS an
        # extra verify-by-GET-before-DELETE beat in the dispatcher: the
        # event is fetched first and its title/start surfaced in the
        # extracted trace so the audit trail captures exactly what was
        # destroyed. Chain-aware — resolves event_id from a prior
        # calendar_read result's parsed id field.
        "name": "calendar_delete",
        "description": "Delete a calendar event by id from a connected Google Calendar. Destructive — requires governor approval per call. Chain-aware: resolves event_id from a prior calendar_read step's results.",
        "status": "active",
        "runner": "backend_python",
        "risk_level": "high",
        "approval_required": True,
        "external_effect": True,
        "cost_type": "free",
        "endpoint": "/api/v1/calendar/today",
        "notes": "R2.4+ (2026-06-02). Governor default-denies. Dispatcher extracts {account, event_id} via gemini_json (disable_thinking=True), validates the account is connected + event_id is non-empty, fetches the event via get_event to confirm it exists, then calls delete_event. Trace captures the event's title/start so audits can see what was deleted.",
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

    # R2.4+ idempotent retirements: capabilities that have been split or
    # replaced by more precise registry entries. deprecate_capability's
    # WHERE clause skips already-deprecated rows so this is a no-op on
    # subsequent boots.
    try:
        from app.core.capabilities import deprecate_capability
        for retired, reason in [
            ("calendar_read_write", "split into calendar_read + calendar_write (R2.4+)"),
        ]:
            if deprecate_capability(retired, reason=reason):
                print(f"[CAPABILITIES_V1] Retired '{retired}' — {reason}")
    except Exception as e:
        print(f"[CAPABILITIES_V1] Retirement step failed: {e}")
