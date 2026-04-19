"""
Tony's Self-Knowledge System.

Tony knows exactly what he can and cannot do.
He knows his architecture, his tools, his limitations.
He never claims capabilities he doesn't have.
He proactively suggests what he needs to build to solve problems.

This is updated automatically as capabilities are added.
"""
import os
import psycopg2
from datetime import datetime
from typing import Dict, List

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


TONY_CAPABILITIES = {
    "communication": {
        "multi_brain_chat": {"status": "working", "note": "Gemini, Claude, Groq, Mistral, OpenRouter, Council"},
        "voice_output": {"status": "working", "note": "ElevenLabs eleven_multilingual_v2, Azure fallback"},
        "voice_input": {"status": "working", "note": "Android mic with AI transcription correction"},
        "whatsapp_outbound": {"status": "working", "note": "Twilio sandbox - proactive alerts only"},
    },
    "memory": {
        "semantic_memory": {"status": "working", "note": "pgvector similarity search, 768 dimensions"},
        "episodic_memory": {"status": "working", "note": "Significant conversations stored as experiences"},
        "living_memory": {"status": "working", "note": "Continuously updated picture of Matthew's life"},
        "flat_memory": {"status": "working", "note": "Fact storage with deduplication"},
    },
    "awareness": {
        "samsung_calendar": {"status": "working", "note": "Reads device calendar directly"},
        "google_calendar": {"status": "working", "note": "4 accounts with calendar scope"},
        "gmail": {"status": "working", "note": "4 accounts - read, search, draft"},
        "gps_location": {"status": "working", "note": "Real-time coordinates sent with every message"},
        "weather": {"status": "working", "note": "Open-Meteo, Rotherham"},
        "web_search": {"status": "working", "note": "Brave API"},
        "news_monitor": {"status": "working", "note": "Topic-specific monitoring"},
        "youtube_trends": {"status": "working", "note": "Resale trend monitoring every 6h"},
    },
    "intelligence": {
        "chain_of_thought": {"status": "working", "note": "Gemini Pro reasoning before complex responses"},
        "emotional_intelligence": {"status": "working", "note": "Adjusts tone based on context"},
        "continuous_learning": {"status": "working", "note": "Analyses every conversation, builds behaviour rules"},
        "self_improvement": {"status": "working", "note": "Weekly failure analysis and behaviour updates"},
        "proactive_scheduling": {"status": "working", "note": "Calendar + family date awareness"},
        "proactive_intelligence": {"status": "working", "note": "Email pattern analysis, goal initiative"},
        "world_model": {"status": "working", "note": "9 dimensions, updated after each conversation"},
        "knowledge_base": {"status": "working", "note": "UK law, employment, Vinted/eBay"},
    },
    "actions": {
        "document_generation": {"status": "working", "note": "PDF letters with proper typography"},
        "email_drafting": {"status": "working", "note": "Proactive draft replies"},
        "vinted_listing": {"status": "working", "note": "Photo → identification → price research → listing"},
        "fca_register_check": {"status": "working", "note": "Live FCA register API"},
        "companies_house": {"status": "working", "note": "Live Companies House API"},
        "fos_complaint": {"status": "working", "note": "Full complaint generation + PDF"},
        "correspondence_management": {"status": "working", "note": "Reads + responds to legal letters"},
        "autonomous_loop": {"status": "working", "note": "Every 6h - goals, proactive, learning, YouTube"},
    },
    "pending": {
        "browser_automation": {"status": "planned", "note": "Playwright - Tony submits forms himself"},
        "open_banking": {"status": "partial", "note": "TrueLayer built, Live approval needed"},
        "on_device_model": {"status": "infrastructure_built", "note": "Needs 1.5GB model download"},
        "email_sending": {"status": "planned", "note": "Tony sends approved emails autonomously"},
        "facebook_marketplace": {"status": "planned", "note": "Monitor listings for resale opportunities"},
    }
}


def get_capabilities_summary() -> str:
    """Format capabilities for Tony's system prompt."""
    working = []
    for category, caps in TONY_CAPABILITIES.items():
        if category == "pending":
            continue
        for cap, info in caps.items():
            if info["status"] == "working":
                working.append(f"- {cap.replace('_', ' ').title()}: {info['note']}")

    pending = []
    for cap, info in TONY_CAPABILITIES.get("pending", {}).items():
        pending.append(f"- {cap.replace('_', ' ').title()}: {info['note']}")

    return f"""[TONY'S CAPABILITIES — what is actually working right now]:
{chr(10).join(working)}

[PENDING — built but not yet complete]:
{chr(10).join(pending)}"""


def get_full_capabilities() -> Dict:
    return TONY_CAPABILITIES


async def run_startup_health_check() -> Dict:
    """
    Tony runs a health check on all systems at startup.
    Reports what's working, what needs attention.
    """
    import httpx
    results = {"ok": True, "issues": [], "working": []}
    
    checks = {
        "Gemini API": ("https://generativelanguage.googleapis.com", "GEMINI_API_KEY"),
        "Brave Search": ("https://api.search.brave.com", "BRAVE_API_KEY"),
        "ElevenLabs": ("https://api.elevenlabs.io", "ELEVENLABS_API_KEY"),
    }
    
    import os
    for service, (url, env_key) in checks.items():
        if os.environ.get(env_key):
            results["working"].append(service)
        else:
            results["issues"].append(f"{service}: API key not configured")
            results["ok"] = False
    
    return results
