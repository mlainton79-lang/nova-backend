"""
Tony's Pattern Recognition Engine.

After enough conversations, Tony knows Matthew better than he realises.

Tony tracks:
- Time patterns (when Matthew messages, when he's stressed)
- Topic patterns (what comes up repeatedly)
- Emotional patterns (what triggers anxiety, what brings energy)
- Decision patterns (how Matthew makes decisions, what he avoids)
- Life rhythm (work cycles, family patterns)

Then Tony uses these patterns to:
- Anticipate needs before they're expressed
- Identify when something is off
- Know the right moment to surface something
- Understand the subtext of messages

This is the closest thing to Tony genuinely knowing a person.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_pattern_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_patterns (
                id SERIAL PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                pattern_key TEXT NOT NULL,
                pattern_value TEXT,
                confidence FLOAT DEFAULT 0.5,
                evidence_count INTEGER DEFAULT 1,
                last_observed TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(pattern_type, pattern_key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_observations (
                id SERIAL PRIMARY KEY,
                observation_type TEXT NOT NULL,
                content TEXT NOT NULL,
                time_of_day INTEGER, -- hour 0-23
                day_of_week INTEGER, -- 0=Monday
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[PATTERNS] Tables initialised")
    except Exception as e:
        print(f"[PATTERNS] Init failed: {e}")


def record_observation(obs_type: str, content: str, hour: int = None, day: int = None):
    """Record a single observation about Matthew."""
    try:
        now = datetime.utcnow()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_observations (observation_type, content, time_of_day, day_of_week)
            VALUES (%s, %s, %s, %s)
        """, (obs_type, content[:300], hour or now.hour, day or now.weekday()))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[PATTERNS] Observation record failed: {e}")


def update_pattern(pattern_type: str, key: str, value: str, confidence_delta: float = 0.1):
    """Update or create a pattern."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_patterns (pattern_type, pattern_key, pattern_value, confidence)
            VALUES (%s, %s, %s, 0.5)
            ON CONFLICT (pattern_type, pattern_key) DO UPDATE SET
                pattern_value = EXCLUDED.pattern_value,
                confidence = LEAST(1.0, tony_patterns.confidence + %s),
                evidence_count = tony_patterns.evidence_count + 1,
                last_observed = NOW()
        """, (pattern_type, key, value, confidence_delta))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[PATTERNS] Pattern update failed: {e}")


async def analyse_message_for_patterns(message: str, hour: int, day: int):
    """Extract patterns from a single message."""
    # Time patterns
    if hour >= 0 and hour <= 4:
        record_observation("time", "late_night_message", hour, day)
        update_pattern("time", "late_night_builder", f"Messages at {hour}:00", 0.05)

    if hour >= 20 and hour <= 23:
        record_observation("time", "evening_message", hour, day)

    # Topic patterns
    topics = {
        "legal": ["fca", "fos", "court", "complaint", "lawyer", "solicitor"],
        "financial": ["money", "pay", "bill", "debt", "afford"],
        "work": ["shift", "care home", "work", "night", "tired"],
        "family": ["georgina", "amelia", "margot", "kids", "family"],
        "nova": ["tony", "nova", "app", "build", "code"],
        "selling": ["vinted", "ebay", "sell", "listing"],
    }

    msg_lower = message.lower()
    for topic, keywords in topics.items():
        if any(k in msg_lower for k in keywords):
            record_observation("topic", topic, hour, day)
            update_pattern("topic", f"frequent_{topic}", f"Discusses {topic} regularly", 0.05)

    # Stress signals
    stress_signals = ["worried", "stressed", "anxious", "can't sleep", "tired",
                     "overwhelmed", "don't know what", "help", "urgent"]
    if any(s in msg_lower for s in stress_signals):
        record_observation("emotional", "stress_signal", hour, day)
        update_pattern("emotional", "stress_pattern", f"Shows stress at hour {hour}", 0.1)


async def get_pattern_insights() -> str:
    """Get pattern insights for Tony's system prompt."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # High confidence patterns
        cur.execute("""
            SELECT pattern_type, pattern_key, pattern_value, confidence, evidence_count
            FROM tony_patterns
            WHERE confidence > 0.6
            ORDER BY confidence DESC
            LIMIT 10
        """)
        patterns = cur.fetchall()

        # Recent observation summary
        cur.execute("""
            SELECT observation_type, COUNT(*) as count,
                   AVG(time_of_day) as avg_hour
            FROM tony_observations
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY observation_type
            ORDER BY count DESC
            LIMIT 5
        """)
        recent = cur.fetchall()

        cur.close()
        conn.close()

        if not patterns and not recent:
            return ""

        lines = ["[TONY'S PATTERN RECOGNITION]:"]

        for obs_type, count, avg_hour in recent:
            lines.append(f"- {obs_type}: {count} times this week (avg hour: {int(avg_hour or 0)}:00)")

        for p_type, key, value, confidence, count in patterns:
            lines.append(f"- {value} (confidence: {confidence:.0%}, seen {count}x)")

        return "\n".join(lines)

    except Exception as e:
        print(f"[PATTERNS] Insights failed: {e}")
        return ""


async def run_pattern_analysis():
    """Weekly deep pattern analysis."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT observation_type, content, time_of_day, day_of_week, created_at
            FROM tony_observations
            WHERE created_at > NOW() - INTERVAL '7 days'
            ORDER BY created_at DESC
            LIMIT 100
        """)
        obs = cur.fetchall()
        cur.close()
        conn.close()

        if not obs:
            return

        obs_text = "\n".join(
            f"[{r[0]}] {r[1]} at hour {r[2]}, day {r[3]}"
            for r in obs[:50]
        )

        prompt = f"""Tony is analysing patterns in Matthew's conversations over the past week.

Observations:
{obs_text}

Identify meaningful patterns:
1. When does Matthew typically message? (time patterns)
2. What topics come up repeatedly?
3. Are there emotional patterns? (when does he seem stressed vs energised?)
4. What does Matthew avoid talking about?
5. What does this tell Tony about how to better help Matthew?

Respond in JSON:
{{
    "key_patterns": [
        {{
            "type": "time/topic/emotional/avoidance",
            "pattern": "description",
            "implication": "what this means for how Tony should behave"
        }}
    ],
    "matthew_rhythm": "description of Matthew's typical week/day pattern",
    "best_time_to_surface_important_things": "when Matthew is most receptive",
    "things_tony_should_proactively_watch": ["specific things to monitor"]
}}"""

        result = await gemini_json(prompt, task="analysis", max_tokens=1024)
        if result:
            # Store key patterns
            for pattern in result.get("key_patterns", []):
                update_pattern(
                    pattern.get("type", "general"),
                    pattern.get("pattern", "")[:100],
                    pattern.get("implication", "")[:200],
                    0.2
                )
            print(f"[PATTERNS] Weekly analysis complete")

    except Exception as e:
        print(f"[PATTERNS] Weekly analysis failed: {e}")
