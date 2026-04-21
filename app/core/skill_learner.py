"""
Skill Learner — Tony proposes new skills from patterns in his own conversations.

Looks for recurring conversation shapes in the diary + episodic memory:
  - Same topic coming up weekly
  - Same type of question where Tony's response template kept working
  - Gap between what Matthew asks and what any existing skill handles

When Tony sees such a pattern, proposes a new SKILL.md. Matthew reviews and
approves. On approval, the skill is written to app/skills/ and becomes
active on next Railway deploy.

Distinct from capability_builder (which builds new API endpoints).
This builds new BEHAVIOURS (skill prompts) — much lower risk, higher leverage.
"""
import os
import httpx
import json
import psycopg2
from datetime import datetime
from typing import Dict, List, Optional


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_skill_proposal_tables():
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_skill_proposals (
                id SERIAL PRIMARY KEY,
                proposed_name TEXT,
                description TEXT,
                triggers JSONB,
                body TEXT,
                rationale TEXT,
                source_conversations JSONB,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed_at TIMESTAMP
            )
        """)
        cur.close()
        conn.close()
        print("[SKILL_LEARNER] Tables initialised")
    except Exception as e:
        print(f"[SKILL_LEARNER] Init failed: {e}")


PATTERN_DETECTION_PROMPT = """You are reviewing a week of Tony's conversations with Matthew. Look for patterns that might become new skills.

A new skill is worth proposing if:
  - Matthew has asked about the same TYPE of thing 3+ times
  - Tony's response template has kept working well
  - No existing skill already handles this well
  - A new skill would materially improve Tony's future responses

Existing skills Tony already has:
{existing_skills}

Recent conversation themes:
{themes}

Return STRICT JSON. If NO pattern merits a new skill, return {{"found": false, "reason": "..."}}.
If a pattern IS worth capturing:

{{
  "found": true,
  "proposed_name": "slug-case-name",
  "description": "one-line summary of when to use",
  "triggers": ["5-10 natural phrases Matthew actually uses"],
  "body": "Markdown content for the SKILL.md — rules, examples, what-not-to-do",
  "rationale": "why this pattern needs a skill, what recurring problem it solves"
}}

Rules:
- Don't propose skills that duplicate existing ones
- Don't propose for one-off situations
- Don't propose for things Tony shouldn't do (medical advice, legal, finance specifics)
- Body should follow Tony's tone rules: short, British, no pet names
- Triggers must be things Matthew actually says, not theoretical phrases"""


async def detect_skill_opportunity() -> Optional[Dict]:
    """
    Analyse recent conversations for a recurring pattern worth capturing.
    Uses diary entries + fact trends.
    """
    try:
        # Check budget
        from app.core.budget_guard import is_autonomous_allowed
        if not is_autonomous_allowed():
            return {"skip": True, "reason": "Budget frozen"}
    except Exception:
        pass

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    # Gather existing skills
    try:
        from app.skills.loader import discover_skills
        existing = discover_skills()
        existing_list = [
            f"{s['name']}: {s['description'][:100]}"
            for s in existing
        ]
    except Exception:
        existing_list = []

    # Gather recent themes from diary
    try:
        from app.core.tony_diary import get_recent_diary
        diary = get_recent_diary(days=7)
        themes = []
        for e in diary:
            if e.get("observations"):
                themes.append(f"{e['date']}: {e['observations']}")
            if e.get("followups"):
                themes.append(f"  followups: {e['followups']}")
        themes_text = "\n".join(themes) if themes else "No recent diary entries"
    except Exception:
        themes_text = "No diary available"

    prompt = PATTERN_DETECTION_PROMPT.format(
        existing_skills="\n".join(existing_list),
        themes=themes_text[:4000],
    )

    try:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 2000, "temperature": 0.3}
                }
            )
            r.raise_for_status()
            response = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Log budget
        try:
            from app.core.budget_guard import log_api_call
            log_api_call("gemini-2.5-flash", "skill_learner", tokens=2000,
                         source="skill_learner")
        except Exception:
            pass

        # Parse
        if response.startswith("```"):
            lines = response.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response = "\n".join(lines).strip()
        first = response.find("{")
        last = response.rfind("}")
        if first < 0 or last < 0:
            return None

        data = json.loads(response[first:last+1])
        return data
    except Exception as e:
        print(f"[SKILL_LEARNER] Detection failed: {e}")
        return None


def save_proposal(data: Dict) -> Optional[int]:
    """Save a proposed skill to the DB for Matthew's review."""
    if not data.get("found"):
        return None

    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_skill_proposals
                (proposed_name, description, triggers, body, rationale)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            data.get("proposed_name", "unnamed")[:100],
            data.get("description", "")[:500],
            json.dumps(data.get("triggers", [])),
            data.get("body", "")[:5000],
            data.get("rationale", "")[:500],
        ))
        new_id = cur.fetchone()[0]
        cur.close()
        conn.close()
        return new_id
    except Exception as e:
        print(f"[SKILL_LEARNER] Save failed: {e}")
        return None


def list_proposals(status: str = "pending") -> List[Dict]:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, proposed_name, description, triggers, body, rationale, created_at
            FROM tony_skill_proposals
            WHERE status = %s
            ORDER BY created_at DESC LIMIT 20
        """, (status,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"id": r[0], "name": r[1], "description": r[2],
             "triggers": r[3], "body": r[4], "rationale": r[5],
             "created_at": str(r[6])}
            for r in rows
        ]
    except Exception:
        return []


async def approve_proposal(proposal_id: int) -> Dict:
    """
    Approve a proposed skill — writes the SKILL.md file, marks approved.
    The new file goes to app/skills/<name>/SKILL.md and gets pushed to GitHub.
    """
    proposals = list_proposals("pending")
    proposal = next((p for p in proposals if p["id"] == proposal_id), None)
    if not proposal:
        return {"ok": False, "error": "Proposal not found"}

    name = proposal["name"]
    if not name.replace("-", "").replace("_", "").isalnum():
        return {"ok": False, "error": "Invalid skill name"}

    # Build SKILL.md content
    description = proposal["description"]
    triggers = proposal["triggers"] if isinstance(proposal["triggers"], list) else []
    body = proposal["body"]

    skill_md = f"""---
name: {name}
description: {description}
version: 0.1.0
triggers:
"""
    for t in triggers:
        skill_md += f"  - {t}\n"
    skill_md += "---\n\n" + body

    # Push to GitHub
    try:
        import base64
        GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
        GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")
        path = f"app/skills/{name}/SKILL.md"
        content_b64 = base64.b64encode(skill_md.encode()).decode()

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.put(
                f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
                json={
                    "message": f"feat: Tony-learned skill — {name}",
                    "content": content_b64,
                }
            )
            if r.status_code not in (200, 201):
                return {"ok": False, "error": f"GitHub push failed: {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"Push failed: {e}"}

    # Mark approved
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_skill_proposals
            SET status = 'approved', reviewed_at = NOW()
            WHERE id = %s
        """, (proposal_id,))
        cur.close()
        conn.close()
    except Exception:
        pass

    return {"ok": True, "name": name, "path": path,
            "note": "Will be active after Railway deploys the new commit"}


def reject_proposal(proposal_id: int) -> Dict:
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE tony_skill_proposals
            SET status = 'rejected', reviewed_at = NOW()
            WHERE id = %s
        """, (proposal_id,))
        cur.close()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
