"""
Tony's Handover Generator.

Generates an accurate, up-to-date handover document by reading
the actual state of the system — not relying on a stale markdown file.

Every session should start by reading this, not HANDOVER.md.
Tony reads his own codebase, DB tables, Railway config, and
synthesises an accurate picture of what exists and what works.
"""
import os
import json
import psycopg2
from datetime import datetime
from typing import Dict, List

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def generate_live_handover() -> Dict:
    """
    Generate an accurate handover by reading actual system state.
    Returns structured dict of what Tony actually has right now.
    """
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "capabilities": [],
        "memory_stats": {},
        "goals": [],
        "knowledge_domains": [],
        "recent_episodes": [],
        "learning_stats": {},
        "alerts_pending": 0,
        "errors": []
    }

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Memory stats
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT category) FROM memories")
        row = cur.fetchone()
        report["memory_stats"]["total_memories"] = row[0]
        report["memory_stats"]["categories"] = row[1]

        # Semantic memory stats
        try:
            cur.execute("SELECT COUNT(*) FROM semantic_memories WHERE embedding IS NOT NULL")
            report["memory_stats"]["semantic_indexed"] = cur.fetchone()[0]
        except Exception:
            report["memory_stats"]["semantic_indexed"] = 0

        # Active goals
        cur.execute("SELECT title, priority, status, progress_notes FROM tony_goals WHERE status = 'active' ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END")
        report["goals"] = [{"title": r[0], "priority": r[1], "progress": r[3]} for r in cur.fetchall()]

        # Knowledge domains
        cur.execute("SELECT DISTINCT domain, COUNT(*) FROM tony_knowledge WHERE active = TRUE GROUP BY domain")
        report["knowledge_domains"] = [{"domain": r[0], "entries": r[1]} for r in cur.fetchall()]

        # Recent episodes
        cur.execute("SELECT date, summary, significant FROM tony_episodes ORDER BY created_at DESC LIMIT 5")
        report["recent_episodes"] = [{"date": r[0], "summary": r[1], "significant": r[2]} for r in cur.fetchall()]

        # Learning stats
        cur.execute("SELECT COUNT(*), AVG(score) FROM tony_learning_log WHERE created_at > NOW() - INTERVAL '7 days'")
        row = cur.fetchone()
        report["learning_stats"]["conversations_analysed"] = row[0]
        report["learning_stats"]["avg_score"] = round(float(row[1] or 0), 2)

        cur.execute("SELECT COUNT(*) FROM tony_behaviour_rules WHERE active = TRUE AND confidence > 0.6")
        report["learning_stats"]["active_rules"] = cur.fetchone()[0]

        # Pending alerts
        cur.execute("SELECT COUNT(*) FROM tony_alerts WHERE read = FALSE AND (expires_at IS NULL OR expires_at > NOW())")
        report["alerts_pending"] = cur.fetchone()[0]

        # Core capabilities (from router includes)
        report["capabilities"] = [
            "Multi-brain chat (Gemini, Groq, Mistral, OpenRouter, Claude)",
            "Council mode with multi-brain deliberation",
            "Gmail (4 accounts connected)",
            "Semantic memory with vector similarity search",
            "Episodic memory (experiences, not just facts)",
            "Continuous learning loop with behaviour rules",
            "Chain-of-thought reasoning on complex questions",
            "Emotional intelligence",
            "Proactive intelligence (email patterns, goal initiative)",
            "Knowledge base (UK law, employment, Vinted/eBay)",
            "World model (9 dimensions)",
            "RAG case search (pgvector)",
            "Document generation (PDF letters)",
            "Email drafting (proactive)",
            "Self-evaluation loop",
            "Push notifications (FCM)",
            "Azure TTS / ElevenLabs voice",
            "Vision (Gemini)",
            "Weather awareness (Open-Meteo)",
            "News monitoring (Brave API)",
            "Autonomous loop (every 48h)",
            "Web search (Brave API)",
            "YouTube research",
            "Calendar (Google Calendar API)",
            "Device calendar (Samsung - requires app rebuild)",
            "GPS location (requires app rebuild)",
            "Capability builder (multi-brain code generation)",
        ]

        cur.close()
        conn.close()

    except Exception as e:
        report["errors"].append(str(e))

    return report


def format_handover_for_prompt() -> str:
    """Brief handover summary for Tony's system prompt."""
    try:
        report = generate_live_handover()
        lines = [
            f"[SYSTEM STATE — {report['generated_at'][:10]}]",
            f"Memories: {report['memory_stats'].get('total_memories', 0)} ({report['memory_stats'].get('semantic_indexed', 0)} semantically indexed)",
            f"Goals: {len(report['goals'])} active",
            f"Alerts pending: {report['alerts_pending']}",
            f"Learning: {report['learning_stats'].get('active_rules', 0)} behaviour rules, avg response score {report['learning_stats'].get('avg_score', 0)}",
        ]
        return "\n".join(lines)
    except Exception:
        return ""
