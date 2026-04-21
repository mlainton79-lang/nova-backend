"""
Skills loader and registry.

Scans the app/skills/ tree at startup, parses each SKILL.md's YAML frontmatter,
and registers skills in the database so Tony can reason about them.

Also provides:
  get_skill_descriptions()  — small summary for Tony's prompt (progressive disclosure level 1)
  load_skill_body(name)     — full SKILL.md instructions when a skill fires (level 2)
  load_skill_reference(name, filename)  — specific reference file (level 3)
"""
import os
import re
import yaml
import psycopg2
from typing import Dict, List, Optional
from pathlib import Path


SKILLS_DIR = Path(__file__).parent


def _parse_frontmatter(text: str) -> Dict:
    """Parse YAML frontmatter from a SKILL.md file. Returns {} if missing."""
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {"_body": text, "_has_frontmatter": False}
    try:
        fm = yaml.safe_load(match.group(1)) or {}
        fm["_body"] = match.group(2).strip()
        fm["_has_frontmatter"] = True
        return fm
    except yaml.YAMLError:
        return {"_body": text, "_has_frontmatter": False}


def discover_skills() -> List[Dict]:
    """Scan app/skills/ for SKILL.md files and return their metadata."""
    skills = []
    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir() or skill_dir.name.startswith("_") or skill_dir.name in ("core",):
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            text = skill_file.read_text()
            meta = _parse_frontmatter(text)
            if not meta.get("_has_frontmatter"):
                continue
            skills.append({
                "name": meta.get("name", skill_dir.name),
                "description": meta.get("description", ""),
                "version": meta.get("version", "0.1.0"),
                "path": str(skill_dir),
                "body": meta["_body"],
                "triggers": meta.get("triggers", []),
            })
        except Exception as e:
            print(f"[SKILLS] Failed to parse {skill_file}: {e}")
    return skills


def register_skills_in_db():
    """Persist skill metadata in DB for retrieval in prompts."""
    skills = discover_skills()
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_skills (
                name TEXT PRIMARY KEY,
                description TEXT,
                version TEXT,
                path TEXT,
                triggers JSONB,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        for s in skills:
            import json as _json
            cur.execute("""
                INSERT INTO tony_skills (name, description, version, path, triggers, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    version = EXCLUDED.version,
                    path = EXCLUDED.path,
                    triggers = EXCLUDED.triggers,
                    updated_at = NOW()
            """, (s["name"], s["description"], s["version"], s["path"],
                  _json.dumps(s.get("triggers", []))))
        cur.close()
        conn.close()
        print(f"[SKILLS] Registered {len(skills)} skills")
        return len(skills)
    except Exception as e:
        print(f"[SKILLS] Registration failed: {e}")
        return 0


def get_skill_descriptions() -> str:
    """Level 1 disclosure: skill names + descriptions, for Tony's system prompt."""
    skills = discover_skills()
    if not skills:
        return ""
    lines = [f"- {s['name']}: {s['description']}" for s in skills]
    return "AVAILABLE SKILLS:\n" + "\n".join(lines)


def load_skill_body(name: str) -> Optional[str]:
    """Level 2 disclosure: full SKILL.md body when a skill fires."""
    for s in discover_skills():
        if s["name"] == name:
            return s["body"]
    return None


def find_matching_skills(user_message: str, limit: int = 3) -> List[Dict]:
    """
    Shallow trigger matching. Tony can use this to decide which skill's body to load.
    Matches user_message against trigger phrases from SKILL.md frontmatter.
    """
    user_lower = user_message.lower()
    matches = []
    for s in discover_skills():
        for trigger in s.get("triggers", []):
            if trigger.lower() in user_lower:
                matches.append(s)
                break
    return matches[:limit]
