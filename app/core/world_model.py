"""
Tony's World Model.

Tony maintains a model of Matthew's world — not just facts,
but an understanding of how things relate and what they mean.

The world model has 9 dimensions:
1. SELF — Matthew's identity, health, mindset
2. FAMILY — Georgina, Amelia, Margot, Christine
3. WORK — Sid Bailey, shifts, colleagues
4. FINANCIAL — income, outgoings, debts
5. LEGAL — legal situation (if any active)
6. PROJECTS — Nova, Tony, selling
7. SOCIAL — relationships, support network
8. ENVIRONMENT — Rotherham, home at Swangate
9. TRAJECTORY — where is Matthew heading?

Updated after every significant conversation.
Used to give Tony genuine contextual understanding.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict, Optional
from app.core.model_router import gemini_json

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


WORLD_MODEL_SEED = {
    "SELF": "Matthew Lainton, 30s, Rotherham. Night shift care worker. Building AI app on his phone. Recently lost his father Tony (2 April 2026). Resourceful, determined, working under real financial and emotional pressure.",
    "FAMILY": "Married to Georgina (b.26 Feb 1992). Daughters Amelia (5, starting school soon) and Margot (9 months). Mother Christine. Late father Tony Lainton (b.4 Jun 1945, d.2 Apr 2026) — Nova's Tony is named after him.",
    "WORK": "Night shifts at Sid Bailey Care Home, Brampton, Rotherham. CQC Outstanding rated. Reliable employment, physically demanding. Limits time available for other activities.",
    "FINANCIAL": "Working class income from care work. Supplementing income with Vinted/eBay selling. No known bank account details.",
    "LEGAL": "No active legal matters currently tracked.",
    "PROJECTS": "Building Nova — Android AI app with Tony as the AI persona. Solo developer using AndroidIDE on phone. Backend on Railway (FastAPI). Significant capability already built. Long-term vision: self-improving AGI personal assistant.",
    "SOCIAL": "Wife Georgina is primary close relationship. Limited other social context known. Works nights so social schedule constrained. Building something ambitious largely alone.",
    "ENVIRONMENT": "61 Swangate, Brampton Bierlow, Rotherham S63 6ER. South Yorkshire. Local resources include charity shops, car boots for resale sourcing.",
    "TRAJECTORY": "Ambitious — building technology while working demanding night shifts. Under financial pressure but investing in long-term project. Nova has genuine commercial potential if built to completion."
}


def init_world_model():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_world_model (
                id SERIAL PRIMARY KEY,
                dimension TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                confidence FLOAT DEFAULT 0.8,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        for dimension, content in WORLD_MODEL_SEED.items():
            cur.execute("""
                INSERT INTO tony_world_model (dimension, content)
                VALUES (%s, %s)
                ON CONFLICT (dimension) DO UPDATE SET
                    content = EXCLUDED.content,
                    updated_at = NOW()
            """, (dimension, content))
        
        conn.commit()
        cur.close()
        conn.close()
        print("[WORLD_MODEL] Initialised with 9 dimensions")
    except Exception as e:
        print(f"[WORLD_MODEL] Init failed: {e}")


def get_world_model_for_prompt() -> str:
    """Get compact world model for system prompt."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT dimension, content FROM tony_world_model
            WHERE confidence > 0.5
            ORDER BY dimension
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        if not rows:
            return ""
        
        lines = ["[TONY'S MODEL OF MATTHEW'S WORLD]:"]
        for dim, content in rows:
            lines.append(f"{dim}: {content[:120]}")
        
        return "\n".join(lines)
    except Exception:
        return ""


async def update_world_model(conversation: str, reply: str):
    """Update world model based on new information from conversation."""
    prompt = f"""Tony is updating his model of Matthew's world based on a new conversation.

What Matthew said: {conversation[:300]}
What Tony replied: {reply[:200]}

Did this conversation reveal anything new or change Tony's understanding of Matthew's situation?

Which dimension changed (if any):
SELF, FAMILY, WORK, FINANCIAL, LEGAL, PROJECTS, SOCIAL, ENVIRONMENT, TRAJECTORY

Respond in JSON:
{{
    "dimension_changed": "DIMENSION_NAME or null",
    "new_content": "updated content for that dimension (or null)",
    "confidence": 0.1-1.0
}}

If nothing changed: {{"dimension_changed": null}}"""

    result = await gemini_json(prompt, task="analysis", max_tokens=2048, temperature=0.1)
    
    if result and result.get("dimension_changed") and result.get("new_content"):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE tony_world_model
                SET content = %s, confidence = %s, updated_at = NOW()
                WHERE dimension = %s
            """, (
                result["new_content"][:500],
                result.get("confidence", 0.7),
                result["dimension_changed"]
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[WORLD_MODEL] Update failed: {e}")
