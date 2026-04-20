"""
Tony's Context Window Manager.

The system prompt is getting long. Long prompts degrade quality.
This module intelligently compresses context based on what's relevant
to the current conversation.

Strategy:
- Core identity: always included (small)
- Matthew's details: always included (small)
- Relevant memories: top 8 by similarity, not 15
- Living memory: only relevant sections, not all 11
- Capabilities: compressed list, not full descriptions
- Knowledge base: only when keywords match
- System state: one line summary only
- Pattern insights: only when high confidence

The goal: same intelligence, smaller prompt, better responses.
"""
import os
from typing import List, Dict, Optional


def compress_living_memory(memory: Dict, query: str) -> str:
    """Return only the living memory sections relevant to this query."""
    query_lower = query.lower()
    
    # Always include these
    always_include = ["LIFE_SUMMARY", "CURRENT_FOCUS", "OPEN_LOOPS"]
    
    # Include based on keywords
    conditional = {
        "LEGAL": ["fca", "fos", "court", "legal", "complaint", "lawyer", "solicitor"],
        "FINANCIAL": ["money", "pay", "bill", "debt", "afford", "bank", "income"],
        "FAMILY": ["georgina", "amelia", "margot", "kids", "family", "wife", "daughter"],
        "WORK": ["shift", "care home", "work", "sid bailey", "cqc"],
        "HEALTH": ["tired", "sleep", "health", "feeling", "stress"],
        "GOALS": ["goal", "plan", "want to", "trying to", "working on"],
        "RECENT_EVENTS": ["yesterday", "today", "this week", "recently", "just"],
    }
    
    include_sections = set(always_include)
    for section, keywords in conditional.items():
        if any(k in query_lower for k in keywords):
            include_sections.add(section)
    
    lines = ["[TONY'S PICTURE OF MATTHEW]:"]
    for section in always_include + list(conditional.keys()):
        if section in include_sections and section in memory and memory[section]:
            content = memory[section][:200]  # Truncate each section
            lines.append(f"{section}: {content}")
    
    return "\n".join(lines)


def get_compressed_capabilities() -> str:
    """Compressed one-line capabilities summary."""
    return """[TONY'S CAPABILITIES]: Multi-brain chat (Gemini/Claude/Groq/Mistral/Council), Gmail (4 accounts), Calendar (Samsung+Google), GPS location, Voice I/O, Vinted/eBay listing automation, FOS complaint generation, FCA register lookup, Companies House, document generation, web search, YouTube monitoring, WhatsApp alerts, semantic memory, learning loop, pattern recognition, self-repair, autonomous every 6h."""


def should_include_knowledge(query: str) -> bool:
    """Only include knowledge base when actually relevant."""
    keywords = [
        "fca", "fos", "conc",
        "vinted", "ebay", "sell", "listing", "cqc", "care home", "rights",
        "employment", "ombudsman"
    ]
    return any(k in query.lower() for k in keywords)


def should_include_codebase(query: str) -> bool:
    """Only include codebase for coding questions."""
    keywords = ["code", "function", "file", "class", "bug", "error", "fix",
                "kotlin", "python", "api", "push", "patch", "build", "nova"]
    return any(k in query.lower() for k in keywords)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


MAX_SYSTEM_PROMPT_TOKENS = 6000  # Keep under 6k tokens for quality


def trim_system_prompt(parts: List[str], query: str) -> str:
    """
    Intelligently trim system prompt parts to stay under token budget.
    Prioritises: identity > Matthew details > relevant context > general context
    """
    joined = "\n\n".join(p for p in parts if p)
    tokens = estimate_tokens(joined)
    
    if tokens <= MAX_SYSTEM_PROMPT_TOKENS:
        return joined
    
    # Need to trim - remove lowest priority sections first
    # Parts are ordered by importance in how they're added in tony.py
    # Trim from the end first (least important added last)
    result_parts = list(parts)
    
    while estimate_tokens("\n\n".join(p for p in result_parts if p)) > MAX_SYSTEM_PROMPT_TOKENS:
        if len(result_parts) <= 3:  # Keep at minimum: identity, Matthew details, honesty
            break
        # Remove the last substantive part
        for i in range(len(result_parts) - 1, -1, -1):
            if result_parts[i] and len(result_parts[i]) > 50:
                result_parts[i] = ""
                break
    
    return "\n\n".join(p for p in result_parts if p)
