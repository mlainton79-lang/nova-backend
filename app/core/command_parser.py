"""
Tony's Command Parser.

Tony recognises specific action commands from Matthew
and executes them directly rather than just talking about them.

Commands Tony understands:
- "approve email [id]" → sends the queued email
- "reject email [id]" → removes from queue
- "show email [id]" → shows the full draft
- "create goal [description]" → creates a new goal
- "complete goal [name]" → marks a goal done
- "remind me [time] about [thing]" → creates a scheduled alert
- "search for [query]" → web search
- "what's in my calendar" → reads calendar
- "check my emails" → scans Gmail

This makes Tony genuinely actionable by voice or text —
Matthew doesn't need to navigate menus.
"""
import re
import os
import psycopg2
from typing import Optional, Dict
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


COMMAND_PATTERNS = [
    # New approval-gated chat send for email drafts (single trigger phrase per v2 design).
    # Anchored — `re.search` is used at the dispatch site, so anchors prevent
    # phrases like "please send draft 5 tomorrow" from accidentally opening a gate.
    (r'^send draft #?(\d+)\.?$', 'send_draft'),
    (r'^send #(\d+)\.?$', 'send_draft'),
    # Drafts review — list pending email drafts so Matthew can pick one to send.
    (r'^show (?:me )?(?:my |the )?drafts\??$', 'show_drafts'),
    (r'^list (?:my |the )?drafts\??$', 'show_drafts'),
    # Inbox scan (read-only) — list recent unread across all four Gmail accounts.
    # No DB writes, no Gemini drafting. Quick "what's new in my inbox".
    (r'^scan (?:my |the )?inbox\??$', 'scan_inbox'),
    (r'^check (?:my |the )?inbox\??$', 'scan_inbox'),
    (r'^read (?:my |the )?inbox\??$', 'scan_inbox'),
    (r"^what(?:'s| is)? in (?:my |the )?inbox\??$", 'scan_inbox'),
    # Scan + draft pipeline — read inbox AND prepare draft replies for the
    # ones that need them. Heavier than `scan inbox` (writes draft rows,
    # uses Gemini); kept on its own explicit phrase so it can't fire by
    # accident on a casual "what's new" query.
    (r'^draft (?:my )?replies\??$', 'scan_and_draft'),
    (r'^scan and draft(?: replies)?\??$', 'scan_and_draft'),
    # Legacy `tony_email_queue` commands — quiesced. The queue has no
    # active producer; the new send path is `send draft N` with explicit
    # human approval. Patterns anchored so they only match when typed as
    # commands, not as substrings of unrelated chat.
    (r'^approve email \d+\.?$', 'legacy_email_quiesced'),
    (r'^send email \d+\.?$', 'legacy_email_quiesced'),
    (r'^reject email \d+\.?$', 'legacy_email_quiesced'),
    (r'^show email \d+\.?$', 'legacy_email_quiesced'),
    (r'^delete email \d+\.?$', 'legacy_email_quiesced'),
    (r'create goal[:\s]+(.+)', 'create_goal'),
    (r'add goal[:\s]+(.+)', 'create_goal'),
    (r'complete goal[:\s]+(.+)', 'complete_goal'),
    (r'mark.*goal.*done[:\s]+(.+)', 'complete_goal'),
    (r'what.s in my calendar', 'read_calendar'),
    (r'check my calendar', 'read_calendar'),
    (r'what have i got (today|tomorrow|this week)', 'read_calendar'),
    (r'^check (?:my |the )?emails?\??$', 'legacy_email_quiesced'),
    (r'^any emails? (?:waiting|pending|to approve)\??$', 'legacy_email_quiesced'),
    # Autonomous build approval
    (r'approve build', 'approve_build'),
    (r'deploy build', 'approve_build'),
    (r'approve.*autonomous.*build', 'approve_build'),
    (r'check.*pending.*build', 'check_builds'),
    (r'what.*build.*waiting', 'check_builds'),
    (r'any.*build.*staging', 'check_builds'),
    (r'what.*tony.*built', 'check_builds'),
    # Clear topic permanently
    (r'get rid of (.+)', 'clear_topic'),
    (r'clear (.+) from (?:your|my) brain', 'clear_topic'),
    (r'clear (?:the )?(.+) topic', 'clear_topic'),
    (r'forget (.+) permanently', 'clear_topic'),
    (r'permanently forget (.+)', 'clear_topic'),
    (r'wipe (.+) from (?:your|my) memory', 'clear_topic'),
    (r'remove (.+) from (?:your|my) memory', 'clear_topic'),
    # Actionable today/now surface
    (r'^(?:now|what now|what can we do now(?: then)?|what should i do now|what needs doing now|what do we do now|where should i start)\??$', 'today_brief'),
    # Low-risk capture into memory
    (r'^(?:remember|note|capture) (?:that |this )?(.+)$', 'capture_note'),
    # Smart briefing on demand
    (r'^(?:what(?:\'s| is)? (?:new|up)|any updates?|anything (?:new|happening)|brief me|give me (?:a )?briefing|what(?:\'s| is)? (?:going on|happening))\??$', 'smart_brief'),
    # Expense summary
    (r'what.*spend.*(?:last|past) (\d+) days?', 'expense_summary'),
    (r'my spending (?:this )?(?:week|month|last (?:week|month))', 'expense_summary'),
    (r'how much have i spent', 'expense_summary'),
    # Email triage
    (r'^(?:urgent emails?|email triage|smart digest|urgent)\??$', 'smart_triage'),
    (r'check.*urgent.*email', 'smart_triage'),
    # Daily review
    (r"^(?:how(?:'s| was) (?:today|the day)|end of day|daily review|what happened today|recap today)\??$", 'daily_review'),
    (r'review (?:the )?day', 'daily_review'),
    # N1.email-draft-A: chat-driven on-demand email reply drafting.
    # Group 1 = search query (sender / subject keywords).
    # Group 2 (optional) = instruction telling Tony what to say.
    (r"draft (?:a |the )?reply to (?:the )?(.+?)(?: email)?(?:\s+saying\s+(.+))?$", 'draft_email_reply'),
    (r"reply to (?:the )?(.+?) email\s+saying\s+(.+)$", 'draft_email_reply'),
    (r"draft (?:an? )?email reply (?:to|about)\s+(.+?)(?:\s+saying\s+(.+))?$", 'draft_email_reply'),
]


def detect_command(message: str) -> Optional[Dict]:
    """Detect if a message contains an action command."""
    msg_lower = message.lower().strip()
    
    for pattern, command_type in COMMAND_PATTERNS:
        match = re.search(pattern, msg_lower)
        if match:
            return {
                "command": command_type,
                "args": match.groups(),
                "original": message
            }
    
    return None


async def execute_command(command: Dict) -> str:
    """Execute a detected command and return Tony's response."""
    cmd = command["command"]
    args = command["args"]
    
    if cmd == "approve_email":
        return await _approve_email(int(args[0]))
    
    elif cmd == "reject_email":
        return await _reject_email(int(args[0]))
    
    elif cmd == "show_email":
        return await _show_email(int(args[0]))
    
    elif cmd == "create_goal":
        return await _create_goal(args[0])
    
    elif cmd == "complete_goal":
        return await _complete_goal(args[0])
    
    elif cmd == "read_calendar":
        return await _read_calendar(command.get("original", ""))
    
    elif cmd == "check_email_queue":
        return await _check_email_queue()

    elif cmd == "approve_build":
        return await _approve_build()

    elif cmd == "check_builds":
        return await _check_pending_builds()

    elif cmd == "clear_topic":
        return await _clear_topic(args[0])

    elif cmd == "smart_brief":
        return await _smart_brief()

    elif cmd == "today_brief":
        return await _today_brief()

    elif cmd == "capture_note":
        return await _capture_note(args[0] if args else "")

    elif cmd == "expense_summary":
        days = int(args[0]) if args and len(args) > 0 and args[0] and str(args[0]).isdigit() else 30
        return await _expense_summary(days)

    elif cmd == "smart_triage":
        return await _smart_triage()

    elif cmd == "daily_review":
        return await _daily_review()

    elif cmd == "draft_email_reply":
        query = args[0] if args and len(args) >= 1 and args[0] else ""
        instruction = args[1] if args and len(args) >= 2 and args[1] else None
        return await _draft_email_reply(query, instruction)

    elif cmd == "send_draft":
        try:
            draft_id = int(args[0])
        except (TypeError, ValueError, IndexError):
            return "I didn't catch the draft ID. Try 'send draft 5' (or whatever the number is)."
        return await _send_draft_request(draft_id)

    elif cmd == "show_drafts":
        return await _show_drafts()

    elif cmd == "scan_inbox":
        return await _scan_inbox()

    elif cmd == "scan_and_draft":
        return await _scan_and_draft()

    elif cmd == "legacy_email_quiesced":
        return await _legacy_email_quiesced()

    return ""


async def _draft_email_reply(query: str, instruction: Optional[str] = None) -> str:
    """
    Chat handler for "draft a reply to ..." — bypasses the autonomous
    classifier and asks Tony to draft directly. Replies in plain text;
    Matthew opens Email Drafts to review/edit/approve/send.

    On multiple_matches, stores a Pending Action so a numeric reply
    ("3", "the third one") resolves to that exact email.
    """
    query = (query or "").strip()
    if not query:
        return "What email do you want me to draft a reply to?"

    from app.core.email_drafter import draft_single_reply
    from app.core.pending_actions import create_pending_action

    result = await draft_single_reply(query, instruction)

    if not result.get("ok"):
        err = result.get("error", "")
        if err == "no_match":
            return (
                f"I couldn't find an email matching '{query}'. "
                f"Try clearer search terms — sender name or subject keywords."
            )
        if err == "multiple_matches":
            candidates = result.get("candidates", [])
            # N1.email-draft-A.fix: persist candidate list so a follow-up
            # numeric reply resolves to the chosen email instead of
            # re-running the search.
            create_pending_action(
                action_type="email_draft_selection",
                original_query=query,
                candidates=candidates,
                instruction=instruction,
            )
            lines = [f"I found {len(candidates)} emails matching '{query}'. Which one?"]
            for i, c in enumerate(candidates, 1):
                sender = (c.get("from", "") or "").split("<")[0].strip() or c.get("from", "(unknown)")
                subject = c.get("subject", "(no subject)")
                lines.append(f"{i}. {sender} — {subject}")
            return "\n".join(lines)
        if err == "search_failed":
            return f"Couldn't search Gmail right now: {result.get('details', 'unknown')}"
        return f"I had trouble drafting that reply: {result.get('details', err or 'unknown')}"

    matched = result.get("matched_email", {})
    sender = (matched.get("from", "") or "").split("<")[0].strip() or matched.get("from", "(unknown)")
    subject = matched.get("subject", "(no subject)")
    return f"Drafted a reply to {sender} re: '{subject}'. Open Email Drafts to review and send."


async def _check_pending_action(message: str) -> Optional[str]:
    """
    N1.email-draft-A.fix: Pending Action Router.

    If a recent pending action is awaiting user response (e.g. "which
    email?"), try to resolve this message as a selection. On clear
    selection, execute the resolution and return the response text.
    On no selection (out of range, ambiguous, unrelated text), return
    None so the message falls through to regex command parsing / LLM.

    Reusable across operator workflows (email draft, Vinted disambiguation,
    calendar selection, approval gates).
    """
    from app.core.pending_actions import (
        get_active_pending_action, consume_pending_action,
        consume_pending_action_atomic, parse_selection, parse_approval,
    )

    pending = get_active_pending_action(session_key="default")
    if not pending:
        return None

    if pending["action_type"] == "email_draft_selection":
        candidates = pending.get("candidates", []) or []
        if not candidates:
            return None
        selection = parse_selection(message, len(candidates))
        if selection is None:
            # Not a clear selection — let it fall through. User might be
            # asking something unrelated, or saying "actually nevermind".
            return None

        chosen = candidates[selection - 1]
        consume_pending_action(pending["id"])

        from app.core.email_drafter import draft_reply_to_message
        result = await draft_reply_to_message(
            account=chosen.get("account", ""),
            message_id=chosen.get("id", ""),
            instruction=pending.get("instruction"),
            original_query=pending.get("original_query"),
        )

        if not result.get("ok"):
            err = result.get("error", "")
            return f"Couldn't draft that one: {result.get('details', err or 'unknown')}"

        matched = result.get("matched_email", {})
        sender = (matched.get("from", "") or "").split("<")[0].strip() or matched.get("from", "(unknown)")
        subject = matched.get("subject", "(no subject)")
        return f"Drafted a reply to {sender} re: '{subject}'. Open Email Drafts to review and send."

    if pending["action_type"] == "email_draft_send_approval":
        candidates = pending.get("candidates", []) or []
        if not candidates:
            return None
        cand = candidates[0]
        draft_id = cand.get("draft_id")
        expected_hash = cand.get("body_hash")
        account = cand.get("account")
        base_meta = {
            "pending_action_id": pending["id"],
            "draft_id": draft_id,
            "account": account,
        }

        intent = parse_approval(message)

        # Unparseable — leave the gate open. Bias is toward NOT sending.
        if intent is None:
            return None

        if intent == "cancel":
            consumed = consume_pending_action_atomic(pending["id"])
            if consumed:
                _emit_gate_event("approval_gate_resolved_cancel", base_meta, severity="info")
            return "OK, not sending. Draft is still in your queue."

        # intent == "confirm"
        consumed = consume_pending_action_atomic(pending["id"])
        if not consumed:
            # Another confirm already won the race. Silent drop.
            _emit_gate_event("approval_gate_double_confirm", base_meta, severity="warning")
            return None

        from app.core.email_drafter import _send_draft_internal
        result = await _send_draft_internal(draft_id, expected_hash=expected_hash)

        if result.get("ok"):
            _emit_gate_event("approval_gate_resolved_send", base_meta, severity="info")
            return f"Sent. Draft #{draft_id} is in your Sent folder."

        reason = result.get("reason", "unknown")
        event_name = {
            "not_pending": "approval_gate_aborted_missing",
            "hash_drift": "approval_gate_aborted_drift",
            "db_error": "approval_gate_claim_failed",
            "send_failed": "approval_gate_send_failed",
            "audit_anomaly": "approval_gate_send_failed",
        }.get(reason, "approval_gate_send_failed")
        _emit_gate_event(event_name, base_meta, severity="warning")

        if reason == "not_pending":
            return "That draft is no longer pending (already sent or dismissed)."
        if reason == "hash_drift":
            return (
                "The draft has changed since I showed it to you. "
                f"Re-issue 'send draft {draft_id}' to see the new version and approve."
            )
        if reason == "audit_anomaly":
            # Email did go out — be honest about it.
            return (
                f"Sent. Draft #{draft_id} is in your Sent folder. "
                "Audit trail had a hiccup; the row may still show as pending — check logs."
            )
        return "Send failed — check Gmail auth. Draft is still pending."

    # Unknown action_type — leave pending as-is (don't consume); fall through.
    return None


def _emit_gate_event(event_name: str, metadata: dict, severity: str = "info") -> None:
    """Best-effort observability for the email send-approval gate. Never raises."""
    try:
        from app.observability import record_run_event, EventSeverity
        sev = {
            "info": EventSeverity.INFO,
            "warning": EventSeverity.WARNING,
            "error": EventSeverity.ERROR,
        }.get(severity, EventSeverity.INFO)
        record_run_event(
            event_type=event_name,
            severity=sev,
            subsystem="email.send_approval",
            message=event_name,
            metadata=metadata,
        )
    except Exception:
        pass


async def _send_draft_request(draft_id: int) -> str:
    """Open an approval gate for an email draft. Shows the draft inline so
    Matthew approves what he sees, then waits for an explicit confirm via
    the Pending Action Router. NEVER sends here.
    """
    from datetime import datetime, timezone
    from app.core.email_drafter import get_draft_for_send, _compute_draft_hash
    from app.core.pending_actions import (
        create_pending_action, consume_pending_actions_by_type,
    )

    draft = get_draft_for_send(draft_id)
    if not draft:
        return f"No pending draft with ID {draft_id} — already sent, dismissed, or never existed."

    subject = draft.get("draft_subject") or ""
    body = draft.get("draft_body") or ""
    account = draft.get("account") or ""
    to_addr = draft.get("draft_to") or ""

    if len(subject) + len(body) > MAX_BODY_CHARS_FOR_CHAT_APPROVAL:
        _emit_gate_event(
            "approval_gate_too_large",
            {"draft_id": draft_id, "account": account,
             "size": len(subject) + len(body)},
            severity="warning",
        )
        return (
            "This draft is too long to safely confirm in chat. "
            "Open Email Drafts to review and send."
        )

    body_hash = _compute_draft_hash(subject, body)

    # Atomically retire any prior approval gate for this session so
    # a new "send draft N" can't race with an old "yes" on a prior draft.
    consume_pending_actions_by_type("email_draft_send_approval", session_key="default")

    candidates = [{
        "draft_id": draft_id,
        "draft_to": to_addr,
        "draft_subject": subject,
        "account": account,
        "body_hash": body_hash,
        "shown_at": datetime.now(timezone.utc).isoformat(),
    }]

    pa_id = create_pending_action(
        action_type="email_draft_send_approval",
        original_query="",
        candidates=candidates,
        ttl_minutes=15,
    )

    if pa_id is None:
        return "Couldn't open the approval gate (database error). Try again."

    _emit_gate_event(
        "approval_gate_opened",
        {"pending_action_id": pa_id, "draft_id": draft_id, "account": account},
        severity="info",
    )

    return (
        f"Ready to send to {to_addr} from {account}:\n\n"
        f"Subject: {subject}\n\n"
        f"{body}\n\n"
        f"Reply \"yes\" to send, \"no\" to cancel."
    )


MAX_BODY_CHARS_FOR_CHAT_APPROVAL = 8192


async def _legacy_email_quiesced() -> str:
    """Quiesce handler for the legacy `tony_email_queue` chat commands
    (approve/send/reject/show/delete email N, check my emails, etc.).

    The queue has no live producer — its scanner (`scan_for_actionable_emails`)
    has been a no-op pass since the drafts brick replaced it, and nothing
    else calls `queue_email_for_approval`. The new send path is the
    approval-gated `send draft N`. HTTP endpoints and the table itself are
    left alone for Android UI compatibility; this handler just closes the
    chat-side dispatch so it can't accidentally route to a future-populated
    queue.
    """
    return (
        "The legacy email queue is no longer used. Try one of these:\n"
        "  'show my drafts'   — list prepared drafts\n"
        "  'scan my inbox'    — read recent unread\n"
        "  'draft replies'    — scan inbox AND prepare draft replies\n"
        "  'send draft N'     — send draft #N (asks for your approval first)\n"
        "Or open Email Drafts in the app."
    )


async def _show_drafts() -> str:
    """List pending email drafts in chat so Matthew can pick one to send.

    Read-only — pulls from get_pending_drafts() which already filters to
    status='pending' and opportunistically reverts any stale 'sending' rows.
    """
    from app.core.email_drafter import get_pending_drafts
    try:
        drafts = get_pending_drafts()
    except Exception as e:
        return f"Couldn't read drafts: {e}"

    if not drafts:
        return "No pending email drafts."

    lines = [f"You have {len(drafts)} pending draft{'s' if len(drafts) != 1 else ''}:"]
    for d in drafts:
        sender = (d.get("from", "") or "").split("<")[0].strip() or d.get("from", "(unknown sender)")
        subject = d.get("original_subject") or d.get("draft_subject") or "(no subject)"
        account = d.get("account") or "?"
        lines.append(f"  #{d['id']} ({account}) — {sender}: {subject}")
    lines.append("")
    lines.append("Say 'send draft N' to open the approval gate for one.")
    return "\n".join(lines)


async def _scan_inbox() -> str:
    """Read-only scan of recent unread email across all configured accounts.

    Uses gmail_service.search_all_accounts with `is:unread newer_than:2d`.
    Does NOT draft replies or modify any DB state. Pair with 'draft replies'
    for the heavier scan-and-draft pipeline.
    """
    from app.core.gmail_service import search_all_accounts
    try:
        results = await search_all_accounts("is:unread newer_than:2d", max_per_account=10)
    except Exception as e:
        return f"Couldn't scan inbox: {e}"

    if not results:
        return "Nothing unread in the last 2 days across any of your accounts."

    by_account: Dict[str, list] = {}
    for r in results:
        acc = r.get("account") or "(unknown account)"
        by_account.setdefault(acc, []).append(r)

    lines = [f"Found {len(results)} unread message{'s' if len(results) != 1 else ''} (last 2 days):"]
    for acc in sorted(by_account.keys()):
        msgs = by_account[acc]
        lines.append("")
        lines.append(f"{acc} — {len(msgs)} unread:")
        for m in msgs[:5]:
            sender = (m.get("from", "") or "").split("<")[0].strip() or "(unknown)"
            subject = (m.get("subject") or "(no subject)")[:80]
            lines.append(f"  • {sender}: {subject}")
        if len(msgs) > 5:
            lines.append(f"  ... and {len(msgs) - 5} more")
    lines.append("")
    lines.append("Say 'draft replies' to have me prepare drafts for any that need responses.")
    return "\n".join(lines)


async def _scan_and_draft() -> str:
    """Run the full scan-and-draft pipeline — read inbox, classify, and
    persist draft replies for emails that need responses. Matthew reviews
    via 'show my drafts' and sends via 'send draft N' (approval gate).
    """
    from app.core.email_drafter import scan_and_draft_replies
    try:
        result = await scan_and_draft_replies()
    except Exception as e:
        return f"Couldn't run the scan-and-draft pipeline: {e}"

    drafts_created = result.get("drafts_created", 0)
    emails_checked = result.get("emails_checked", 0)
    errors = result.get("errors", []) or []

    lines = [
        f"Scanned {emails_checked} email{'s' if emails_checked != 1 else ''}; "
        f"prepared {drafts_created} draft{'s' if drafts_created != 1 else ''}."
    ]
    if drafts_created:
        lines.append("Say 'show my drafts' to review, 'send draft N' to send.")
    if errors:
        lines.append(f"({len(errors)} error{'s' if len(errors) != 1 else ''} during scan — check logs.)")
    return "\n".join(lines)


async def _approve_build() -> str:
    """Promote staging branch to main — deploy Tony's autonomous build."""
    try:
        from app.core.tony_self_builder import promote_staging_to_main, get_pending_staging_builds
        # First check there's something to approve
        pending = await get_pending_staging_builds()
        if not pending or pending[0].get("commits_ahead", 0) == 0:
            return "There's nothing in staging waiting to be approved. Tony hasn't built anything new yet."

        p = pending[0]
        result = await promote_staging_to_main()
        if result.get("ok"):
            files = ", ".join(p.get("files_changed", []))
            return (
                f"Done. Tony's autonomous build has been deployed to production.\n\n"
                f"**Merged:** {result.get('message', '')[:100]}\n"
                f"**Files:** {files}\n\n"
                f"Railway will redeploy in about 90 seconds."
            )
        else:
            return f"Couldn't merge staging to main: {result.get('error', 'unknown error')}"
    except Exception as e:
        return f"Build approval failed: {e}"


async def _check_pending_builds() -> str:
    """Show what Tony has built autonomously that's waiting in staging."""
    try:
        from app.core.tony_self_builder import get_pending_staging_builds
        pending = await get_pending_staging_builds()
        if not pending or "error" in pending[0]:
            err = pending[0].get("error", "unknown") if pending else "no data"
            return f"Couldn't check staging branch: {err}"

        p = pending[0]
        ahead = p.get("commits_ahead", 0)

        if ahead == 0:
            return "Nothing in staging — Tony hasn't built anything new since the last approval."

        files = "\n".join(f"  • {f}" for f in p.get("files_changed", []))
        latest = p.get("latest_commit", "unknown")

        return (
            f"Tony has **{ahead} commit{'s' if ahead != 1 else ''}** in staging waiting for your approval.\n\n"
            f"**Latest build:** {latest}\n\n"
            f"**Files changed:**\n{files}\n\n"
            f"Say **approve build** to deploy it, or leave it and I'll keep building."
        )
    except Exception as e:
        return f"Couldn't check pending builds: {e}"


async def _approve_email(queue_id: int) -> str:
    """Tony sends an approved email."""
    try:
        from app.core.email_agent import approve_and_send
        sent = await approve_and_send(queue_id)
        if sent:
            return f"Done — email {queue_id} sent."
        return f"Couldn't send email {queue_id}. It may have already been sent or the ID is wrong."
    except Exception as e:
        return f"Failed to send email: {e}"


async def _reject_email(queue_id: int) -> str:
    """Remove an email from the queue."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE tony_email_queue SET approval_status = 'rejected' WHERE id = %s",
            (queue_id,)
        )
        conn.commit()
        cur.close()
        conn.close()
        return f"Email {queue_id} removed from the queue."
    except Exception as e:
        return f"Failed: {e}"


async def _show_email(queue_id: int) -> str:
    """Show the full draft of a queued email."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT to_address, subject, body, draft_reason FROM tony_email_queue WHERE id = %s",
            (queue_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return f"**Email draft {queue_id}**\nTo: {row[0]}\nSubject: {row[1]}\n\nReason: {row[3]}\n\n---\n{row[2][:1500]}"
        return f"No email found with ID {queue_id}."
    except Exception as e:
        return f"Failed: {e}"


async def _create_goal(description: str) -> str:
    """Create a new goal."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tony_goals (title, priority, status) VALUES (%s, 'normal', 'active') RETURNING id",
            (description[:200],)
        )
        goal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return f"Goal created: '{description}'. I'll start working on it in the next autonomous cycle."
    except Exception as e:
        return f"Failed to create goal: {e}"


async def _complete_goal(name: str) -> str:
    """Mark a goal as complete."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE tony_goals SET status = 'completed' WHERE LOWER(title) LIKE %s AND status = 'active' RETURNING title",
            (f"%{name.lower()[:30]}%",)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if row:
            return f"Marked '{row[0]}' as complete."
        return f"Couldn't find an active goal matching '{name}'."
    except Exception as e:
        return f"Failed: {e}"


async def _read_calendar(message: str = "") -> str:
    """Read Samsung-synced calendar context for the requested range."""
    try:
        from app.core.samsung_calendar import read_calendar_for_message
        return await read_calendar_for_message(message or "today")
    except Exception as e:
        return f"Couldn't read calendar: {e}"


async def _check_email_queue() -> str:
    """Check pending email approvals."""
    try:
        from app.core.email_agent import get_pending_approvals
        emails = await get_pending_approvals()
        if not emails:
            return "No emails waiting for your approval."
        lines = [f"You have {len(emails)} email(s) waiting:"]
        for e in emails[:3]:
            lines.append(f"• ID {e['id']}: {e['subject'][:50]} (to {e['to'][:30]})")
        lines.append("\nSay 'show email [id]' to see the draft, or 'approve email [id]' to send.")
        return "\n".join(lines)
    except Exception as e:
        return f"Couldn't check emails: {e}"



async def _clear_topic(topic: str) -> str:
    """Permanently wipe a topic from Tony's active recall."""
    topic = topic.strip().rstrip(".,!?").strip()
    if not topic:
        return "Tell me specifically what to clear."

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Mark all matching alerts read + expired
        cur.execute("""
            UPDATE tony_alerts
            SET read = TRUE, expires_at = NOW() - INTERVAL '1 hour'
            WHERE (title ILIKE %s OR body ILIKE %s OR source ILIKE %s)
            AND (read = FALSE OR expires_at > NOW())
        """, (f"%{topic}%", f"%{topic}%", f"%{topic}%"))
        alerts_cleared = cur.rowcount

        # Add 30-day topic ban
        cur.execute("""
            INSERT INTO tony_topic_bans
            (chat_session_id, topic, phrase_that_triggered, expires_at)
            VALUES (NULL, %s, %s, NOW() + INTERVAL '30 days')
        """, (topic, f"Matthew: clear {topic}"))

        # Demote semantic memories
        memories_demoted = 0
        try:
            cur.execute("""
                UPDATE tony_semantic_memory
                SET importance = 0
                WHERE content ILIKE %s
            """, (f"%{topic}%",))
            memories_demoted = cur.rowcount
        except Exception:
            pass

        # Mark goals dormant
        goals_dormant = 0
        try:
            cur.execute("""
                UPDATE tony_goals
                SET status = 'dormant'
                WHERE (title ILIKE %s OR description ILIKE %s)
                AND status != 'completed'
            """, (f"%{topic}%", f"%{topic}%"))
            goals_dormant = cur.rowcount
        except Exception:
            pass

        conn.commit()
        cur.close()
        conn.close()

        return (
            f"Done. Wiped '{topic}' from active memory.\n"
            f"- {alerts_cleared} alerts cleared\n"
            f"- {memories_demoted} memories demoted\n"
            f"- {goals_dormant} goals marked dormant\n"
            f"- 30-day ban added so it won't resurface\n\n"
            f"Won't bring it up again unless you do."
        )
    except Exception as e:
        return f"Couldn't clear that — DB error: {e}"


async def _smart_brief() -> str:
    """Run the intelligent briefing."""
    try:
        from app.core.intelligent_briefing import get_intelligent_briefing
        result = await get_intelligent_briefing()
        return result.get("briefing", "All clear. Nothing needing you.")
    except Exception as e:
        return f"Couldn't generate brief — {str(e)[:100]}"


async def _today_brief() -> str:
    """Run the actionable today surface."""
    try:
        from app.core.today_brief import get_today_brief
        result = await get_today_brief()
        return _format_today_brief_response(result)
    except Exception as e:
        return f"Today brief error — {str(e)[:100]}"


def _format_today_brief_response(result: Dict) -> str:
    briefing = str(result.get("briefing") or "All clear.").strip()
    next_actions = [
        str(action).strip()
        for action in result.get("next_actions", [])
        if str(action).strip() and str(action).strip() != "No urgent action surfaced."
    ]
    flags = [
        str(flag.get("message") or "").strip()
        for flag in result.get("health_flags", [])
        if isinstance(flag, dict) and str(flag.get("message") or "").strip()
    ]

    parts = [briefing]
    if next_actions:
        parts.append("Next:\n" + "\n".join(f"- {action}" for action in next_actions))
    if flags:
        parts.append("Flags:\n" + "\n".join(f"- {message}" for message in flags))
    return "\n\n".join(parts)


async def _capture_note(text: str) -> str:
    """Capture a low-risk note into memory."""
    try:
        from app.core.capture import capture_note
        result = await capture_note(text)
    except Exception as e:
        return f"Capture failed — {str(e)[:100]}"

    if result.get("ok") and result.get("saved"):
        return "Captured."
    if result.get("ok"):
        return "Already captured, or nothing new was saved."
    return f"Not captured — {result.get('error', 'unknown error')}"


async def _expense_summary(days: int = 30) -> str:
    """Summarise recent spending."""
    try:
        from app.core.receipt_extractor import get_expense_summary
        summary = get_expense_summary(days=days)
        if summary.get("error") or summary.get("count", 0) == 0:
            return f"No expenses tracked in the last {days} days. Photograph a receipt and I'll start logging."
        total = summary["total"]
        top_cats = summary.get("by_category", [])[:3]
        cats_str = ", ".join(
            f"{c['category']} £{c['total']:.0f}" for c in top_cats
        ) if top_cats else "uncategorised"
        return (f"Last {days} days: £{total:.2f} across {summary['count']} receipts. "
                f"Biggest: {cats_str}.")
    except Exception as e:
        return f"Couldn't get expenses — {str(e)[:100]}"


async def _smart_triage() -> str:
    """Run smart email triage and summarise urgent items."""
    try:
        from app.core.email_triage import get_smart_digest
        digest = await get_smart_digest()
        if not digest.get("ok"):
            return f"Couldn't check emails — {digest.get('error', 'unknown')}"
        if digest.get("count", 0) == 0:
            return "All caught up. No unread emails."
        return digest.get("digest", "Checked. Nothing urgent.")
    except Exception as e:
        return f"Triage error — {str(e)[:100]}"


async def _daily_review() -> str:
    """Run today's review."""
    try:
        from app.core.daily_review import get_daily_review
        result = await get_daily_review()
        return _format_daily_review_response(result)
    except Exception as e:
        return f"Couldn't run daily review — {str(e)[:100]}"


def _format_daily_review_response(result: Dict) -> str:
    review = str(result.get("review") or "Quiet one today.").strip()
    actions = [
        str(action).strip()
        for action in result.get("follow_up_actions", [])
        if str(action).strip() and str(action).strip() != "No follow-up action surfaced."
    ]
    if not actions:
        return review
    return review + "\n\nFollow-up:\n" + "\n".join(f"- {action}" for action in actions)
