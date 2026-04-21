"""
Endpoints for inspecting Tony's skills system.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.skills.loader import (
    discover_skills, get_skill_descriptions, find_matching_skills, load_skill_body
)

router = APIRouter()


@router.get("/skills")
async def list_skills(_=Depends(verify_token)):
    """List all registered skills and their metadata."""
    skills = discover_skills()
    return {
        "ok": True,
        "count": len(skills),
        "skills": [
            {
                "name": s["name"],
                "description": s["description"],
                "version": s["version"],
                "triggers": s.get("triggers", []),
                "body_chars": len(s["body"]),
            }
            for s in skills
        ],
    }


@router.get("/skills/{name}")
async def get_skill(name: str, _=Depends(verify_token)):
    """Get the full body of a specific skill."""
    body = load_skill_body(name)
    if not body:
        return {"ok": False, "error": f"Skill {name!r} not found"}
    return {"ok": True, "name": name, "body": body}


@router.post("/skills/match")
async def match_skill(payload: dict, _=Depends(verify_token)):
    """Test which skills would trigger for a given message."""
    message = payload.get("message", "")
    matches = find_matching_skills(message, limit=5)
    return {
        "ok": True,
        "message": message,
        "matches": [{"name": m["name"], "description": m["description"]} for m in matches],
    }
