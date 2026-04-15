import os
import httpx
import json

async def extract_and_save_instant_memory(message: str, reply: str) -> list:
    try:
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
        GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        if not GEMINI_API_KEY:
            return []

        prompt = f"""Extract any personal facts about Matthew from this conversation that are worth remembering long-term.
Return a JSON array of strings. Each string is one fact. Return [] if nothing worth saving.
Only extract clear, specific facts — not opinions or temporary states.

User said: {message[:500]}
Tony replied: {reply[:500]}

Return only valid JSON array, nothing else."""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 512}
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return []
            parts = candidates[0].get("content", {}).get("parts", [])
            text = " ".join(p.get("text", "") for p in parts if "text" in p).strip()
            text = text.replace("```json", "").replace("```", "").strip()
            facts = json.loads(text)
            if isinstance(facts, list):
                return [f for f in facts if isinstance(f, str) and f.strip()]
            return []
    except Exception as e:
        print(f"[INSTANT_MEMORY] failed: {e}")
        return []
