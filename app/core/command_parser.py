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
    (r'approve email (\d+)', 'approve_email'),
    (r'send email (\d+)', 'approve_email'),
    (r'reject email (\d+)', 'reject_email'),
    (r'show email (\d+)', 'show_email'),
    (r'delete email (\d+)', 'reject_email'),
    (r'create goal[:\s]+(.+)', 'create_goal'),
    (r'add goal[:\s]+(.+)', 'create_goal'),
    (r'complete goal[:\s]+(.+)', 'complete_goal'),
    (r'mark.*goal.*done[:\s]+(.+)', 'complete_goal'),
    (r'what.s in my calendar', 'read_calendar'),
    (r'check my calendar', 'read_calendar'),
    (r'what have i got (today|tomorrow|this week)', 'read_calendar'),
    (r'check.*emails?', 'check_email_queue'),
    (r'any.*emails? (waiting|pending|to approve)', 'check_email_queue'),
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
        return await _read_calendar()
    
    elif cmd == "check_email_queue":
        return await _check_email_queue()

    elif cmd == "approve_build":
        return await _approve_build()

    elif cmd == "check_builds":
        return await _check_pending_builds()

    elif cmd == "clear_topic":
        return await _clear_topic(args[0])

    return ""


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


async def _read_calendar() -> str:
    """Read today's calendar."""
    try:
        from app.core.calendar_service import get_todays_events
        events = await get_todays_events()
        if not events:
            return "Nothing in your calendar today."
        lines = ["Here's what's in your calendar:"]
        for e in events[:5]:
            lines.append(f"• {e.get('time', '')} — {e.get('title', '')}")
        return "\n".join(lines)
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
