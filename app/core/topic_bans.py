"""
Topic bans — Matthew can tell Tony to stop bringing up a subject,
and Tony honours it for the rest of the conversation session.

Usage:
  Matthew says: "don't bring up the CCJ again", "forget Western Circle for now"
  detect_topic_ban() returns "CCJ" or "Western Circle"
  store_ban(chat_session_id, topic)
  get_active_bans(chat_session_id) returns the list for injection into prompt

Bans expire after 6 hours automatically to avoid permanently silencing things
if Matthew forgets about them.
"""
import os
import re
import psycopg2
from typing import List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_topic_bans_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_topic_bans (
                id SERIAL PRIMARY KEY,
                chat_session_id TEXT,
                topic TEXT NOT NULL,
                phrase_that_triggered TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '6 hours'),
                active BOOLEAN DEFAULT TRUE
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bans_active_session
            ON tony_topic_bans (chat_session_id, active, expires_at)
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[TOPIC_BANS] Init failed: {e}")


# Phrases that indicate Matthew wants to stop talking about something
BAN_TRIGGERS = [
    r"don'?t\s+bring\s+up\s+(?:the\s+)?(.+?)(?:\s+again|\s*$|[.!?])",
    r"don'?t\s+mention\s+(?:the\s+)?(.+?)(?:\s+again|\s*$|[.!?])",
    r"stop\s+bringing\s+up\s+(?:the\s+)?(.+?)(?:\s*$|[.!?])",
    r"stop\s+talking\s+about\s+(?:the\s+)?(.+?)(?:\s*$|[.!?])",
    r"stop\s+mentioning\s+(?:the\s+)?(.+?)(?:\s*$|[.!?])",
    # forget/forgot (typo tolerance): captures "forget X until", "forgot X until"
    r"forg[eo]t\s+(?:that\s+|the\s+|about\s+)?(.+?)\s+(?:until|for now|unless|for a bit)",
    r"drop\s+(?:the\s+)?(.+?)\s+(?:topic|for now|subject)",
    r"leave\s+(?:the\s+)?(.+?)\s+(?:alone|out of it)",
    r"fuck\s+off\s+about\s+(?:the\s+)?(.+?)(?:\s*$|[.!?])",
    r"quit\s+(?:going on about|mentioning)\s+(?:the\s+)?(.+?)(?:\s*$|[.!?])",
    # Resolve "that" references to the most recently banned topic by context
    # Falls through to the generic forget capture above
]


def detect_topic_ban(message: str) -> Optional[str]:
    """
    Detect if the user is asking Tony to stop mentioning a topic.
    Returns the topic name or None.
    """
    if not message:
        return None
    msg_lower = message.lower().strip()
    for pattern in BAN_TRIGGERS:
        match = re.search(pattern, msg_lower, re.IGNORECASE)
        if match:
            topic = match.group(1).strip()
            # Clean up the captured topic
            topic = re.sub(r"\s+", " ", topic)
            # Strip common trailing words
            topic = re.sub(r"\s+(again|for now|please|mate|son|lad)$", "", topic, flags=re.IGNORECASE)
            topic = topic.strip(" .,!?")
            # Filter out useless captures (pronouns, empty, common stop words)
            STOP_TOPICS = {"that", "it", "this", "them", "those", "these", "one"}
            if (2 <= len(topic) <= 80 and
                topic.lower() not in STOP_TOPICS and
                len(topic.split()) <= 6):
                return topic
    return None


def store_ban(chat_session_id: Optional[str], topic: str, phrase: str):
    """Store a topic ban for this session."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Check for existing active ban on same topic — extend if found
        cur.execute("""
            SELECT id FROM tony_topic_bans
            WHERE topic ILIKE %s AND active = TRUE AND expires_at > NOW()
            AND (chat_session_id = %s OR chat_session_id IS NULL)
            LIMIT 1
        """, (topic, chat_session_id))
        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE tony_topic_bans
                SET expires_at = NOW() + INTERVAL '6 hours',
                    phrase_that_triggered = %s
                WHERE id = %s
            """, (phrase[:200], existing[0]))
        else:
            cur.execute("""
                INSERT INTO tony_topic_bans (chat_session_id, topic, phrase_that_triggered)
                VALUES (%s, %s, %s)
            """, (chat_session_id, topic[:80], phrase[:200]))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[TOPIC_BANS] Stored ban on '{topic}'")
    except Exception as e:
        print(f"[TOPIC_BANS] Store failed: {e}")


def get_active_bans(chat_session_id: Optional[str] = None) -> List[str]:
    """Get currently active topic bans for injection into the prompt."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Return session-specific bans + global bans (session_id NULL)
        cur.execute("""
            SELECT DISTINCT topic FROM tony_topic_bans
            WHERE active = TRUE
            AND expires_at > NOW()
            AND (chat_session_id = %s OR chat_session_id IS NULL)
            ORDER BY topic
        """, (chat_session_id,))
        topics = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return topics
    except Exception as e:
        print(f"[TOPIC_BANS] Get failed: {e}")
        return []


def clear_ban(topic: str, chat_session_id: Optional[str] = None):
    """Manually clear a ban (e.g. when Matthew brings the topic up himself)."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_topic_bans
            SET active = FALSE
            WHERE topic ILIKE %s
            AND (chat_session_id = %s OR chat_session_id IS NULL)
            AND active = TRUE
        """, (topic, chat_session_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[TOPIC_BANS] Clear failed: {e}")


def check_and_clear_if_user_raises_topic(message: str, chat_session_id: Optional[str] = None) -> List[str]:
    """
    If Matthew brings up a banned topic himself, auto-clear that ban.
    Returns the list of cleared topics.
    """
    bans = get_active_bans(chat_session_id)
    cleared = []
    msg_lower = message.lower()
    for topic in bans:
        # Simple word-boundary match — if Matthew used the topic name, he's re-raised it
        if re.search(r"\b" + re.escape(topic.lower()) + r"\b", msg_lower):
            clear_ban(topic, chat_session_id)
            cleared.append(topic)
    return cleared
