"""
Unified Retrieval — single-call semantic search across all of Tony's memory.

Instead of prompt_assembler querying facts, semantic_memory, document_memory, 
and diary separately (each with their own filtering), this does one call that:
  1. Queries all four sources in parallel
  2. Scores each result by similarity + source_quality
  3. Deduplicates (same fact stated in facts + memory)
  4. Returns top N ranked by combined score

Designed to be called from prompt_assembler as an optional 'better retrieval'
path, with the existing per-source injection as fallback.
"""
import asyncio
from typing import Dict, List, Optional


# Relative quality weights — how much to trust each source for relevance
SOURCE_WEIGHTS = {
    "facts": 1.0,       # explicit triples, high confidence
    "documents": 0.9,   # user-uploaded, verified
    "semantic": 0.8,    # extracted from conversations
    "diary": 0.7,       # Tony's interpretation (subjective)
    "episodic": 0.85,   # significant moments
}


async def _search_facts(query: str, top_k: int = 5) -> List[Dict]:
    """Get matching facts."""
    try:
        from app.core.fact_extractor import get_facts_about
        # Get facts about query if query is a name, else get all recent
        results = get_facts_about(query, limit=top_k)
        if not results:
            # Fallback — check if any recent fact mentions the query
            import psycopg2, os
            conn = psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")
            cur = conn.cursor()
            cur.execute("""
                SELECT subject, predicate, object, confidence FROM tony_facts
                WHERE (subject ILIKE %s OR object ILIKE %s OR predicate ILIKE %s)
                  AND superseded_by IS NULL
                ORDER BY confidence DESC, created_at DESC LIMIT %s
            """, (f"%{query[:50]}%", f"%{query[:50]}%", f"%{query[:50]}%", top_k))
            rows = cur.fetchall()
            cur.close()
            conn.close()
            results = [{"subject": r[0], "predicate": r[1], "object": r[2],
                        "confidence": float(r[3])} for r in rows]
        return [
            {
                "text": f"{r.get('subject','Matthew')} {r.get('predicate','')} {r.get('object','')}",
                "source": "facts",
                "similarity": r.get("confidence", 0.7),
                "metadata": r,
            }
            for r in results
        ]
    except Exception:
        return []


async def _search_semantic(query: str, top_k: int = 5) -> List[Dict]:
    try:
        from app.core.semantic_memory import search_memories
        results = await search_memories(query, top_k=top_k)
        return [
            {
                "text": r.get("text", "") if isinstance(r, dict) else str(r),
                "source": "semantic",
                "similarity": r.get("similarity", 0.5) if isinstance(r, dict) else 0.5,
                "metadata": r if isinstance(r, dict) else {},
            }
            for r in results if (r if isinstance(r, dict) else str(r))
        ]
    except Exception:
        return []


async def _search_documents(query: str, top_k: int = 5) -> List[Dict]:
    try:
        from app.core.document_memory import search_documents
        results = await search_documents(query, top_k=top_k)
        return [
            {
                "text": r.get("text", ""),
                "source": "documents",
                "similarity": r.get("similarity", 0.5),
                "metadata": {"doc_name": r.get("doc_name"), "doc_type": r.get("doc_type")},
            }
            for r in results
        ]
    except Exception:
        return []


async def _search_diary(query: str, top_k: int = 3) -> List[Dict]:
    try:
        from app.core.tony_diary import get_recent_diary
        entries = get_recent_diary(days=14)
        # Simple keyword match against observations
        query_lower = query.lower()
        results = []
        for e in entries:
            obs = (e.get("observations") or "")
            followups = (e.get("followups") or "")
            # Score by overlap
            score = 0
            for word in query_lower.split():
                if len(word) > 3:
                    if word in obs.lower(): score += 0.3
                    if word in followups.lower(): score += 0.4
            if score > 0:
                text = f"From {e['date']}: {obs}"
                results.append({
                    "text": text,
                    "source": "diary",
                    "similarity": min(score, 1.0),
                    "metadata": {"date": e["date"]},
                })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]
    except Exception:
        return []


def _dedupe(results: List[Dict]) -> List[Dict]:
    """Remove near-duplicate results (same text, different source)."""
    seen = set()
    unique = []
    for r in results:
        text = r.get("text", "").strip().lower()
        if not text:
            continue
        # Use first 50 chars as dedup key
        key = text[:50]
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


async def unified_search(query: str, top_k: int = 8) -> List[Dict]:
    """
    Search all memory sources in parallel, fuse results, rank by combined score.
    Returns top_k ranked results with source attribution.
    """
    if not query or len(query.strip()) < 2:
        return []

    # Parallel fetch
    results = await asyncio.gather(
        _search_facts(query, top_k=5),
        _search_semantic(query, top_k=5),
        _search_documents(query, top_k=3),
        _search_diary(query, top_k=3),
        return_exceptions=True,
    )

    # Flatten
    all_results = []
    for r in results:
        if isinstance(r, list):
            all_results.extend(r)

    if not all_results:
        return []

    # Apply source weight to similarity
    for r in all_results:
        source = r.get("source", "unknown")
        weight = SOURCE_WEIGHTS.get(source, 0.5)
        r["final_score"] = r.get("similarity", 0) * weight

    # Sort by final score
    all_results.sort(key=lambda x: x.get("final_score", 0), reverse=True)

    # Dedupe
    deduped = _dedupe(all_results)

    return deduped[:top_k]


def format_unified_results(results: List[Dict]) -> str:
    """Format unified results for injection into a prompt."""
    if not results:
        return ""

    lines = ["[RELEVANT CONTEXT — from memory, facts, documents, diary]"]
    by_source = {}
    for r in results:
        src = r.get("source", "unknown")
        by_source.setdefault(src, []).append(r)

    # Show in source-clustered way, most relevant first
    for source in ["facts", "documents", "semantic", "episodic", "diary"]:
        items = by_source.get(source, [])
        if not items:
            continue
        for r in items[:3]:
            text = r.get("text", "").strip()[:300]
            if text:
                lines.append(f"  [{source}] {text}")

    return "\n".join(lines)
