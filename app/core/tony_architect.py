"""
Tony's Architecture Understanding Engine.

Tony understands his own architecture deeply.
He knows every file, what it does, how it connects,
and what to change to add or improve capabilities.

This is different from reading files — this is genuine understanding
of the system as a whole, maintained as a living model.

Tony uses this to:
1. Plan self-modifications safely
2. Avoid breaking existing functionality
3. Identify the correct place to add new capabilities
4. Understand the impact of changes before making them
5. Debug his own issues when they occur

Updated automatically when Tony builds new capabilities.
"""
import os
import json
import base64
import httpx
import psycopg2
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "mlainton79-lang/nova-backend")


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_architect_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_architecture (
                id SERIAL PRIMARY KEY,
                component TEXT NOT NULL UNIQUE,
                description TEXT,
                dependencies TEXT[],
                exposes TEXT[],
                file_path TEXT,
                last_updated TIMESTAMP DEFAULT NOW(),
                notes TEXT
            )
        """)
        
        # Seed with known architecture
        components = [
            ("chat_stream", "Primary chat endpoint with streaming. Handles all preprocessing concurrently.",
             ["tony.py", "memory.py", "emotional_intelligence.py", "reasoning.py", "brave_search.py"],
             ["/api/v1/chat/stream"], "app/api/v1/endpoints/chat_stream.py",
             "Main conversation handler. All context injection happens here."),
            ("council", "Multi-brain deliberation. All providers vote, Claude synthesises.",
             ["council.py (provider)", "tony.py"],
             ["/api/v1/council"], "app/api/v1/endpoints/council.py",
             "Slowest but highest quality. Now handles images via vision preprocessing."),
            ("tony_prompts", "System prompt builder. Assembles all context for every message.",
             ["memory.py", "living_memory.py", "self_knowledge.py", "knowledge_base.py"],
             ["build_system_prompt()"], "app/prompts/tony.py",
             "Critical file. Every part of Tony's context assembled here. Now has token trimming."),
            ("autonomous_loop", "Runs every 6h. Tony works without being asked.",
             ["goals.py", "proactive.py", "learning.py", "youtube_monitor.py", "agi_loop.py"],
             ["main.py startup task"], "app/main.py",
             "All autonomous behaviour triggered here. Now includes AGI self-building loop."),
            ("semantic_memory", "Vector similarity memory retrieval. 768-dim embeddings.",
             ["pgvector extension"],
             ["search_memories()", "add_semantic_memory()"], "app/core/semantic_memory.py",
             "Retrieves most relevant memories not just most recent. Migrates flat memories on startup."),
            ("living_memory", "Continuously updated picture of Matthew's life. 11 structured sections.",
             ["gemini (Pro)", "world_model.py"],
             ["get_living_memory_for_prompt()", "update_from_conversation()"], "app/core/living_memory.py",
             "Updates after every conversation. Most important context for Tony understanding Matthew."),
            ("agi_self_builder", "Tony builds new capabilities autonomously.",
             ["tony_self_builder.py", "code_reviewer.py", "github API"],
             ["tony_build_capability()", "run_agi_improvement_cycle()"],
             "app/core/tony_self_builder.py",
             "Full pipeline: assess → decide → research → generate → review → debug → deploy → test."),
            ("model_router", "Routes tasks to appropriate model (Pro vs Flash).",
             ["Gemini API"],
             ["gemini()", "gemini_json()", "choose_model()"], "app/core/model_router.py",
             "Pro for complex reasoning/legal/documents. Flash for fast tasks."),
        ]
        
        for comp in components:
            cur.execute("""
                INSERT INTO tony_architecture 
                (component, description, dependencies, exposes, file_path, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (component) DO UPDATE SET
                    description = EXCLUDED.description,
                    notes = EXCLUDED.notes,
                    last_updated = NOW()
            """, comp)
        
        conn.commit()
        cur.close()
        conn.close()
        print("[ARCHITECT] Architecture model initialised")
    except Exception as e:
        print(f"[ARCHITECT] Init failed: {e}")


async def get_architecture_for_task(task: str) -> str:
    """Get relevant architecture context for a given task."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT component, description, file_path, notes
            FROM tony_architecture
            ORDER BY last_updated DESC
        """)
        all_components = cur.fetchall()
        cur.close()
        conn.close()
        
        if not all_components:
            return ""
        
        # Find relevant components
        task_lower = task.lower()
        relevant = []
        for comp, desc, filepath, notes in all_components:
            if any(word in task_lower for word in comp.split('_')):
                relevant.append(f"- {comp}: {desc}\n  File: {filepath}\n  Notes: {notes}")
            elif desc and any(word in desc.lower() for word in task_lower.split()):
                relevant.append(f"- {comp}: {desc}\n  File: {filepath}")
        
        if not relevant:
            # Return top-level overview
            relevant = [f"- {c[0]}: {c[1]}" for c in all_components[:5]]
        
        return "TONY'S ARCHITECTURE CONTEXT:\n" + "\n".join(relevant[:5])
    except Exception:
        return ""


async def analyse_change_impact(proposed_change: str, files_to_change: List[str]) -> Dict:
    """
    Before Tony makes a change, analyse what else might break.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT component, dependencies, exposes FROM tony_architecture")
        all_components = cur.fetchall()
        cur.close()
        conn.close()
        
        arch_summary = "\n".join(
            f"- {c[0]}: depends on {c[1]}, exposes {c[2]}"
            for c in all_components
        )
    except Exception:
        arch_summary = "Architecture data unavailable"
    
    prompt = f"""Tony is planning a code change. Analyse the impact.

Proposed change: {proposed_change}
Files to be modified: {', '.join(files_to_change)}

Architecture:
{arch_summary}

What else might break? What should Tony check before making this change?

Respond in JSON:
{{
    "risk_level": "low/medium/high",
    "components_at_risk": ["component names"],
    "things_to_check": ["specific things to verify"],
    "safe_to_proceed": true/false,
    "recommendation": "proceed/add_tests/review_carefully/abort"
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=512) or {
        "risk_level": "unknown", "safe_to_proceed": True
    }


async def update_architecture(component: str, description: str, filepath: str, notes: str = ""):
    """Tony updates his own architecture model when he builds something new."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tony_architecture (component, description, file_path, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (component) DO UPDATE SET
                description = EXCLUDED.description,
                file_path = EXCLUDED.file_path,
                notes = EXCLUDED.notes,
                last_updated = NOW()
        """, (component, description, filepath, notes))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[ARCHITECT] Updated architecture: {component}")
    except Exception as e:
        print(f"[ARCHITECT] Update failed: {e}")
