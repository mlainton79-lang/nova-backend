"""
Tony's Episodic Memory.

Tony remembers specific conversations as experiences, not just facts.

Episodic memory is different from semantic memory:
- Semantic: "Matthew works night shifts"  
- Episodic: "On 15 April Matthew mentioned he was exhausted after three 
             consecutive night shifts and worried about his dad's anniversary"

Episodic memories preserve:
- The emotional context of a conversation
- What Matthew seemed to be feeling
- What Tony said and whether it helped
- What was resolved vs left open
- Time and context

This is what makes Tony feel like he genuinely remembers
rather than just having access to a database.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_episodic_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_episodic_memory (
                id SERIAL PRIMARY KEY,
                episode_date DATE NOT NULL,
                title TEXT,
                summary TEXT NOT NULL,
                matthew_state TEXT,
                emotional_tone TEXT,
                topics TEXT[],
                resolved BOOLEAN DEFAULT FALSE,
                open_threads TEXT[],
                significance FLOAT DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[EPISODIC] Tables initialised")
    except Exception as e:
        print(f"[EPISODIC] Init failed: {e}")


async def create_episode(
    conversation_history: List[Dict],
    session_date: str = None
) -> Optional[Dict]:
    """
    Convert a conversation into an episodic memory.
    Preserves the experience, not just the facts.
    """
    if not conversation_history or len(conversation_history) < 2:
        return None
    
    conv_text = "\n".join(
        f"{'Matthew' if m.get('role') == 'user' else 'Tony'}: {m.get('content', '')[:150]}"
        for m in conversation_history[:10]
    )
    
    prompt = f"""Convert this conversation into an episodic memory for Tony.

Conversation:
{conv_text}

Create a rich episodic memory that captures the experience, not just facts.

Respond in JSON:
{{
    "title": "short memorable title for this episode",
    "summary": "2-3 sentence narrative summary — what happened, what mattered",
    "matthew_state": "how Matthew seemed (tired/stressed/positive/frustrated/worried/etc)",
    "emotional_tone": "overall emotional tone of the conversation",
    "topics": ["main topics discussed"],
    "resolved": true/false,
    "open_threads": ["things left unresolved that Tony should remember"],
    "significance": 0.1-1.0
}}"""
    
    return await gemini_json(prompt, task="analysis", max_tokens=512)


async def store_episode(episode: Dict, date: str = None) -> bool:
    """Store an episodic memory."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_episodic_memory
            (episode_date, title, summary, matthew_state, emotional_tone,
             topics, resolved, open_threads, significance)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            date or datetime.utcnow().date(),
            episode.get("title", "")[:100],
            episode.get("summary", "")[:500],
            episode.get("matthew_state", "")[:100],
            episode.get("emotional_tone", "")[:50],
            episode.get("topics", [])[:5],
            episode.get("resolved", False),
            episode.get("open_threads", [])[:3],
            episode.get("significance", 0.5)
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[EPISODIC] Store failed: {e}")
        return False


async def get_relevant_episodes(query: str, limit: int = 3) -> str:
    """Get episodes relevant to the current conversation."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Get recent significant episodes
        cur.execute("""
            SELECT title, summary, matthew_state, episode_date, open_threads
            FROM tony_episodic_memory
            WHERE significance > 0.4
            ORDER BY episode_date DESC, significance DESC
            LIMIT %s
        """, (limit,))
        episodes = cur.fetchall()
        cur.close()
        conn.close()
        
        if not episodes:
            return ""
        
        lines = ["[TONY REMEMBERS]:"]
        for title, summary, state, date, threads in episodes:
            lines.append(f"\n{date} — {title}")
            lines.append(f"  {summary}")
            if state:
                lines.append(f"  Matthew was: {state}")
            if threads:
                lines.append(f"  Still open: {', '.join(threads[:2])}")
        
        return "\n".join(lines)
    except Exception as e:
        print(f"[EPISODIC] Get failed: {e}")
        return ""


async def process_conversation_for_episode(message: str, reply: str) -> bool:
    """
    Create an episodic memory from a single message/reply pair.
    Called after every conversation — only stores if the exchange is significant enough.
    Significance threshold: 0.4 (filters out trivial exchanges like "hi" / "ok")
    """
    # Quick significance pre-check — don't waste a Gemini call on trivial exchanges
    trivial_triggers = ["hi", "hello", "ok", "thanks", "cheers", "alright", "bye"]
    if (len(message.strip()) < 20 and
            any(message.strip().lower().startswith(t) for t in trivial_triggers)):
        return False

    episode = await create_episode([
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply}
    ])

    if not episode:
        return False

    significance = episode.get("significance", 0.0)
    if significance < 0.4:
        return False  # Not worth storing — low significance exchange

    return await store_episode(episode)
