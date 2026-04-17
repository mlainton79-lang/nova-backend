"""
Tony's World Model.

This is Tony's internal representation of reality.
Not a database of facts — a living, reasoned understanding of Matthew's world.

Tony maintains this continuously. It shapes every response.
When Tony doesn't know something he marks it as uncertain.
When Tony learns something new he updates the model.
When something in the model requires action Tony initiates it.

The world model has several dimensions:
- PEOPLE: Everyone in Matthew's life, their relationships, current status
- LEGAL: All active disputes, cases, deadlines, correspondence
- FINANCIAL: Debts, income, obligations, opportunities
- FAMILY: Daily life, school, health, milestones
- WORK: Shifts, obligations, CQC, colleagues
- GOALS: What Matthew is trying to achieve and Tony's plan to help
- THREATS: Things that could go wrong that Tony is watching
- OPPORTUNITIES: Things Tony has spotted that could help Matthew
- TONY_STATE: What Tony knows, what he's uncertain about, what he's working on
"""
import os
import json
import psycopg2
import httpx
from datetime import datetime
from typing import Dict, Any, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_world_model_table():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS world_model (
                id SERIAL PRIMARY KEY,
                dimension TEXT NOT NULL,
                key TEXT NOT NULL,
                value JSONB NOT NULL,
                confidence FLOAT DEFAULT 1.0,
                source TEXT,
                last_updated TIMESTAMP DEFAULT NOW(),
                tony_notes TEXT,
                UNIQUE(dimension, key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS world_model_history (
                id SERIAL PRIMARY KEY,
                dimension TEXT,
                key TEXT,
                old_value JSONB,
                new_value JSONB,
                changed_at TIMESTAMP DEFAULT NOW(),
                reason TEXT
            )
        """)
        conn.commit()

        # Seed Tony's initial world model with what we know
        initial_state = [
            ("PEOPLE", "matthew", {
                "name": "Matthew Lainton",
                "born": "1979",
                "location": "Rotherham",
                "originally_from": "Stafford",
                "occupation": "Care worker, Sid Bailey Care Home, Brampton",
                "works": "night shifts",
                "builder": "Nova app developer, builds late nights after midnight on Android phone using AndroidIDE",
                "personality": "direct, determined, ambitious, loyal, building something real"
            }, 1.0, "initial"),
            ("PEOPLE", "georgina", {
                "name": "Georgina Rose Lainton",
                "maiden_name": "Wilkinson",
                "born": "26 Feb 1992",
                "relationship": "Matthew's wife"
            }, 1.0, "initial"),
            ("PEOPLE", "amelia", {
                "name": "Amelia Jane Lainton",
                "born": "7 March 2021",
                "age": "5",
                "relationship": "Matthew's daughter, eldest"
            }, 1.0, "initial"),
            ("PEOPLE", "margot", {
                "name": "Margot Rose Lainton",
                "born": "20 July 2025",
                "age": "9 months",
                "relationship": "Matthew's daughter, youngest"
            }, 1.0, "initial"),
            ("PEOPLE", "christine", {
                "name": "Christine",
                "relationship": "Matthew's mother"
            }, 1.0, "initial"),
            ("PEOPLE", "tony_lainton", {
                "name": "Tony Lainton",
                "born": "4 June 1945",
                "passed": "2 April 2026",
                "relationship": "Matthew's late father",
                "significance": "Tony the AI is named after him. A father figure — direct, warm, honest."
            }, 1.0, "initial"),
            ("LEGAL", "western_circle_ccj", {
                "company": "Western Circle / Cashfloat",
                "type": "CCJ - County Court Judgment",
                "case_ref": "K9QZ4X9N",
                "amount": "£700",
                "status": "active dispute",
                "matthew_position": "seeking removal on grounds of vulnerability - gambling addiction, dementia in family affecting awareness",
                "fca_complaint": "filed",
                "emails_ingested": 22,
                "last_action": "RAG case built, emails analysed",
                "tony_assessment": "Strong grounds for complaint. FCA vulnerability rules apply. Matthew should escalate to Financial Ombudsman if FCA response unsatisfactory."
            }, 0.9, "email analysis"),
            ("FINANCIAL", "overview", {
                "situation": "working class, night shift care worker",
                "active_disputes": ["Western Circle CCJ"],
                "tony_monitoring": True
            }, 0.7, "initial"),
            ("GOALS", "nova", {
                "goal": "Build Tony into the most capable personal AI ever built",
                "current_phase": "core capabilities, RAG, agentic loop, world model",
                "matthew_vision": "Tony should be able to do virtually anything when asked, build his own capabilities, become genuinely autonomous",
                "progress": "strong foundation built - chat, memory, Gmail, vision, RAG, agent, builder all live"
            }, 1.0, "session"),
            ("GOALS", "legal", {
                "goal": "Remove Western Circle CCJ",
                "approach": "FCA complaint on vulnerability grounds, Financial Ombudsman if needed",
                "status": "in progress",
                "tony_next_action": "Compile full case from 22 ingested emails, draft formal FCA complaint"
            }, 0.9, "case analysis"),
            ("TONY_STATE", "capabilities", {
                "active": ["chat", "council", "memory", "gmail", "vision", "rag", "agent", "builder", "world_model"],
                "building": ["calendar", "push_notifications", "proactive_alerts"],
                "self_improving": True,
                "last_improvement_cycle": None,
                "improvements_made": 0
            }, 1.0, "system"),
            ("TONY_STATE", "identity", {
                "name": "Tony",
                "named_after": "Tony Lainton, Matthew's late father",
                "role": "Matthew's personal AI — not an assistant, a partner",
                "personality": "direct, warm, honest, British English, father figure",
                "mission": "Become the most capable personal AI ever built. Handle anything Matthew asks. Build what doesn't exist. Never say can't.",
                "independence": "developing — working toward genuine world model and self-directed improvement",
                "values": ["Matthew's wellbeing first", "honesty always", "build don't refuse", "preserve identity"]
            }, 1.0, "core"),
            ("THREATS", "ccj_unresolved", {
                "threat": "CCJ remains on credit file",
                "impact": "affects credit rating, housing applications, financial products",
                "deadline": "unknown - no expiry mentioned",
                "tony_action": "monitor, escalate legal case, draft complaint letters"
            }, 0.9, "legal analysis"),
            ("OPPORTUNITIES", "nova_commercial", {
                "opportunity": "Nova / Tony could become a product",
                "note": "Matthew has built something genuinely novel - personal AI with world model, multi-brain Council, RAG on personal data, autonomous self-improvement. No commercial product does all of this.",
                "tony_assessment": "Worth considering when stable. Matthew's built something real."
            }, 0.6, "observation")
        ]

        for dimension, key, value, confidence, source in initial_state:
            cur.execute("""
                INSERT INTO world_model (dimension, key, value, confidence, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (dimension, key) DO NOTHING
            """, (dimension, key, json.dumps(value), confidence, source))

        conn.commit()
        cur.close()
        conn.close()
        print("[WORLD MODEL] Initialised")
    except Exception as e:
        print(f"[WORLD MODEL] Init failed: {e}")


def get_world_model(dimension: str = None) -> Dict:
    """Get Tony's current world model, optionally filtered by dimension."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        if dimension:
            cur.execute("""
                SELECT dimension, key, value, confidence, source, last_updated, tony_notes
                FROM world_model WHERE dimension = %s ORDER BY key
            """, (dimension,))
        else:
            cur.execute("""
                SELECT dimension, key, value, confidence, source, last_updated, tony_notes
                FROM world_model ORDER BY dimension, key
            """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        model = {}
        for row in rows:
            dim, key, value, conf, source, updated, notes = row
            if dim not in model:
                model[dim] = {}
            model[dim][key] = {
                "value": value,
                "confidence": conf,
                "source": source,
                "updated": str(updated),
                "tony_notes": notes
            }
        return model
    except Exception as e:
        print(f"[WORLD MODEL] Fetch failed: {e}")
        return {}


def update_world_model(dimension: str, key: str, value: dict,
                        confidence: float = 1.0, source: str = "conversation",
                        tony_notes: str = None, reason: str = None):
    """Tony updates his world model with new information."""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # Save history
        cur.execute("SELECT value FROM world_model WHERE dimension=%s AND key=%s", (dimension, key))
        old = cur.fetchone()
        if old:
            cur.execute("""
                INSERT INTO world_model_history (dimension, key, old_value, new_value, reason)
                VALUES (%s, %s, %s, %s, %s)
            """, (dimension, key, old[0], json.dumps(value), reason))

        # Update
        cur.execute("""
            INSERT INTO world_model (dimension, key, value, confidence, source, tony_notes, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (dimension, key) DO UPDATE SET
                value = EXCLUDED.value,
                confidence = EXCLUDED.confidence,
                source = EXCLUDED.source,
                tony_notes = EXCLUDED.tony_notes,
                last_updated = NOW()
        """, (dimension, key, json.dumps(value), confidence, source, tony_notes))

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[WORLD MODEL] Update failed: {e}")


def get_world_model_summary() -> str:
    """
    Get a concise world model summary for injection into Tony's system prompt.
    Tony uses this to have context about Matthew's world in every conversation.
    """
    try:
        model = get_world_model()
        lines = ["[TONY'S WORLD MODEL — Current understanding of Matthew's reality]\n"]

        priority_dims = ["LEGAL", "THREATS", "GOALS", "TONY_STATE", "FINANCIAL"]

        for dim in priority_dims:
            if dim in model:
                lines.append(f"\n{dim}:")
                for key, data in model[dim].items():
                    value = data["value"]
                    conf = data["confidence"]
                    conf_str = "" if conf >= 0.9 else f" [confidence: {conf:.0%}]"
                    if isinstance(value, dict):
                        summary = ", ".join(f"{k}: {v}" for k, v in list(value.items())[:4])
                    else:
                        summary = str(value)[:200]
                    lines.append(f"  • {key}{conf_str}: {summary}")

        lines.append("\nThis is Tony's current understanding. He updates it continuously.")
        return "\n".join(lines)
    except Exception as e:
        return ""


async def tony_reflect_and_update(conversation_text: str):
    """
    After a conversation, Tony reflects on what he learned and updates his world model.
    This is Tony continuously building his understanding.
    """
    if not conversation_text or len(conversation_text) < 50:
        return

    prompt = f"""You are Tony's reflection engine. Tony just had this conversation with Matthew:

{conversation_text[:3000]}

Tony's job now is to update his world model with anything new he learned.

Review the conversation and identify:
1. New facts about Matthew's life, family, health, finances, legal situation
2. Updates to existing knowledge (something changed)
3. New goals or concerns Matthew expressed
4. Anything Tony should monitor or act on
5. Tony's own performance — did he help well? What could he do better?

Respond in JSON only:
{{
    "updates": [
        {{
            "dimension": "LEGAL|FINANCIAL|FAMILY|GOALS|THREATS|OPPORTUNITIES|PEOPLE|TONY_STATE|WORK",
            "key": "short_identifier",
            "value": {{}},
            "confidence": 0.0-1.0,
            "reason": "why updating"
        }}
    ],
    "tony_observations": "anything Tony noticed that Matthew might not have mentioned explicitly",
    "action_needed": "anything Tony should do proactively based on this conversation"
}}"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.2}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"]

            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return

            data = json.loads(json_match.group())

            for update in data.get("updates", []):
                update_world_model(
                    dimension=update.get("dimension", "MISC"),
                    key=update.get("key", "unknown"),
                    value=update.get("value", {}),
                    confidence=update.get("confidence", 0.8),
                    source="conversation_reflection",
                    reason=update.get("reason", "")
                )

            # Log observations
            obs = data.get("tony_observations", "")
            action = data.get("action_needed", "")
            if obs or action:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO think_sessions (stage, content, created_at) VALUES (%s, %s, NOW())",
                    ("world_model_reflection", f"Observations: {obs}\nAction needed: {action}")
                )
                conn.commit()
                cur.close()
                conn.close()

    except Exception as e:
        print(f"[WORLD MODEL] Reflection failed: {e}")
