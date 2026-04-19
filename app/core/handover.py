"""
Tony's Handover System.

Every time Tony restarts (Railway redeploys), he needs context
about what was happening. The handover brief gives him that.

It assembles:
- Open goals and their status
- Pending email drafts awaiting approval
- Recent important events
- Active alerts
- What was being discussed recently
- Tony's commitments from the last week

This ensures Tony picks up exactly where he left off
rather than starting fresh each time.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def get_handover_brief() -> Dict:
    """Build a complete handover brief."""
    brief = {
        "generated_at": datetime.utcnow().isoformat(),
        "open_goals": [],
        "pending_emails": [],
        "recent_alerts": [],
        "memory_stats": {},
        "tony_commitments": "",
        "weekly_strategy": "",
    }
    
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Open goals
        cur.execute("""
            SELECT title, priority, progress_notes
            FROM tony_goals WHERE status = 'active'
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
            LIMIT 5
        """)
        brief["open_goals"] = [
            {"title": r[0], "priority": r[1], "progress": r[2] or "None"}
            for r in cur.fetchall()
        ]
        
        # Pending email approvals
        cur.execute("""
            SELECT id, to_address, subject, priority
            FROM tony_email_queue
            WHERE approval_status = 'pending'
            ORDER BY created_at DESC LIMIT 3
        """)
        brief["pending_emails"] = [
            {"id": r[0], "to": r[1], "subject": r[2], "priority": r[3]}
            for r in cur.fetchall()
        ]
        
        # Recent unread alerts
        cur.execute("""
            SELECT title, body, priority, source, created_at
            FROM tony_alerts
            WHERE read = FALSE
            ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, created_at DESC
            LIMIT 5
        """)
        brief["recent_alerts"] = [
            {"title": r[0], "body": r[1][:100], "priority": r[2], "source": r[3]}
            for r in cur.fetchall()
        ]
        
        # Memory stats
        cur.execute("SELECT COUNT(*) FROM memories")
        mem_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tony_episodic_memory")
        ep_count = cur.fetchone()[0] if cur.rowcount else 0
        brief["memory_stats"] = {
            "total_memories": mem_count,
            "episodic_memories": ep_count
        }
        
        # Tony's commitments from last weekly strategy
        cur.execute("""
            SELECT content FROM tony_living_memory
            WHERE section = 'WEEKLY_STRATEGY'
        """)
        row = cur.fetchone()
        if row:
            brief["weekly_strategy"] = row[0][:200]
        
        cur.close()
        conn.close()
        
    except Exception as e:
        brief["error"] = str(e)
    
    return brief


def format_handover_for_prompt() -> str:
    """Format handover as compact system prompt section."""
    try:
        brief = get_handover_brief()
        lines = ["[TONY'S HANDOVER STATE]:"]
        
        if brief.get("open_goals"):
            urgent = [g for g in brief["open_goals"] if g["priority"] in ("urgent", "high")]
            if urgent:
                lines.append("Active priorities: " + " | ".join(
                    f"{g['title']} ({g['priority']})" for g in urgent[:3]
                ))
        
        if brief.get("pending_emails"):
            lines.append(f"Emails awaiting approval: {len(brief['pending_emails'])} (check /email-agent/pending)")
        
        if brief.get("recent_alerts"):
            high = [a for a in brief["recent_alerts"] if a["priority"] in ("urgent", "high")]
            if high:
                lines.append("Unread alerts: " + " | ".join(a["title"] for a in high[:2]))
        
        if brief.get("weekly_strategy"):
            lines.append(f"This week: {brief['weekly_strategy'][:100]}")
        
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        return ""


def generate_live_handover() -> Dict:
    """Alias for get_handover_brief - used by handover endpoint."""
    return get_handover_brief()
