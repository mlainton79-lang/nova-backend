"""
Tony's Memory Consolidation Engine.

Over time Tony accumulates thousands of memories.
Raw deduplication isn't enough — Tony needs to:
1. Merge related memories into stronger, cleaner facts
2. Promote frequently accessed memories to higher priority
3. Archive old memories that are no longer relevant
4. Build composite memories from patterns
5. Identify contradictions and resolve them

This is analogous to how human memory consolidates during sleep.
Tony does this weekly to maintain a clean, high-quality memory store.
"""
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List
from app.core.model_router import gemini_json, gemini

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


async def consolidate_memories() -> Dict:
    """
    Full memory consolidation cycle.
    Merges, promotes, archives, and resolves contradictions.
    """
    results = {"merged": 0, "archived": 0, "promoted": 0, "resolved": 0}

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get all memories grouped by category
        cur.execute("""
            SELECT id, category, text, created_at
            FROM memories
            ORDER BY category, created_at DESC
        """)
        all_memories = cur.fetchall()

        if len(all_memories) < 5:
            cur.close()
            conn.close()
            return results

        # Group by category
        by_category = {}
        for mid, cat, text, created in all_memories:
            by_category.setdefault(cat, []).append((mid, text, created))

        for category, memories in by_category.items():
            if len(memories) < 3:
                continue

            # Check for contradictions
            texts = [m[1] for m in memories[:10]]
            texts_str = "\n".join(f"- {t}" for t in texts)

            consolidation_prompt = f"""Tony is consolidating his memories about Matthew.

Category: {category}
Memories:
{texts_str}

Tasks:
1. Are any of these contradictory? (e.g., "Matthew works nights" and "Matthew works days")
2. Can any be merged into a single, cleaner memory?
3. Which are outdated or no longer relevant?

Respond in JSON:
{{
    "contradictions": [["memory1 text", "memory2 text"]],
    "to_merge": [["memory1", "memory2", "merged result"]],
    "to_archive": ["memory text that's outdated"],
    "canonical": "the single best memory representing this category"
}}

If nothing to do: {{"contradictions": [], "to_merge": [], "to_archive": [], "canonical": null}}"""

            result = await gemini_json(consolidation_prompt, task="analysis", max_tokens=512)

            if result:
                # Handle merges
                for merge_set in result.get("to_merge", [])[:2]:
                    if len(merge_set) >= 3:
                        merged_text = merge_set[-1]
                        # Delete old, add merged
                        for old_text in merge_set[:-1]:
                            cur.execute(
                                "DELETE FROM memories WHERE text = %s AND category = %s",
                                (old_text, category)
                            )
                        cur.execute(
                            "INSERT INTO memories (category, text) VALUES (%s, %s)",
                            (category, merged_text[:1000])
                        )
                        results["merged"] += 1

                # Handle archives (mark as old by category)
                for archive_text in result.get("to_archive", [])[:2]:
                    cur.execute(
                        "UPDATE memories SET category = %s WHERE text = %s",
                        (f"archived_{category}", archive_text)
                    )
                    results["archived"] += 1

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print(f"[MEMORY_CONSOLIDATOR] Failed: {e}")

    print(f"[MEMORY_CONSOLIDATOR] Consolidated: {results}")
    return results


async def build_composite_memories() -> List[str]:
    """
    Build high-level composite memories from patterns.
    E.g., "Matthew consistently messages late at night" from many late-night messages.
    """
    composites = []

    try:
        conn = get_conn()
        cur = conn.cursor()

        # Get observation patterns
        cur.execute("""
            SELECT observation_type, COUNT(*) as count,
                   AVG(time_of_day) as avg_hour,
                   STRING_AGG(content, ' | ' ORDER BY created_at DESC) as samples
            FROM tony_observations
            WHERE created_at > NOW() - INTERVAL '14 days'
            GROUP BY observation_type
            HAVING COUNT(*) >= 3
        """)
        patterns = cur.fetchall()
        cur.close()
        conn.close()

        for obs_type, count, avg_hour, samples in patterns:
            if count >= 5:
                # Strong enough pattern to memorise
                composite = f"Pattern ({count} observations): Matthew {obs_type.replace('_', ' ')} "
                if avg_hour:
                    composite += f"typically around {int(avg_hour):02d}:00. "
                composite += f"Examples: {samples[:100]}"

                # Add to semantic memory
                from app.core.semantic_memory import add_semantic_memory
                await add_semantic_memory("pattern", composite, importance=1.5)
                composites.append(composite)

    except Exception as e:
        print(f"[MEMORY_CONSOLIDATOR] Composite build failed: {e}")

    return composites


async def run_memory_consolidation() -> Dict:
    """Full consolidation run."""
    results = {}

    try:
        consolidation = await consolidate_memories()
        results["consolidation"] = consolidation
    except Exception as e:
        results["consolidation_error"] = str(e)

    try:
        composites = await build_composite_memories()
        results["composites_built"] = len(composites)
    except Exception as e:
        results["composite_error"] = str(e)

    return results
