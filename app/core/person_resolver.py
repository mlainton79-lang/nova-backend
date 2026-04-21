"""
Person Resolver — maps any name variant to the canonical person.

When a document mentions "Miss Wilkinson", "Mrs Lainton", "Georgina W", etc.,
Tony should recognise all as Georgina. This walks the fact store to build a 
lookup: variant -> canonical_person.
"""
import os
import psycopg2
from typing import Dict, Optional, List


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def resolve_name(name_fragment: str) -> Optional[Dict]:
    """
    Given a name or name fragment, return what we know about that person.
    Returns {canonical_name, aliases, relationships, facts} or None.
    """
    if not name_fragment or len(name_fragment.strip()) < 2:
        return None

    fragment = name_fragment.strip().lower()

    # Known family members and their variants
    known = {
        "matthew": {
            "canonical": "Matthew",
            "variants": ["matthew", "matthew lainton", "matt"],
        },
        "georgina": {
            "canonical": "Georgina",
            "variants": ["georgina", "georgina rose", "georgina lainton",
                         "georgina wilkinson", "georgina rose lainton",
                         "georgina rose wilkinson", "g lainton",
                         "miss wilkinson", "mrs lainton", "wilkinson",
                         "georgie", "gi"],
        },
        "amelia": {
            "canonical": "Amelia",
            "variants": ["amelia", "amelia jane", "amelia lainton",
                         "amelia jane lainton", "millie", "amy"],
        },
        "margot": {
            "canonical": "Margot",
            "variants": ["margot", "margot rose", "margot lainton",
                         "margot rose lainton"],
        },
        "christine": {
            "canonical": "Christine",
            "variants": ["christine", "chris", "mum", "mom", "mother"],
        },
        "tony_lainton": {
            "canonical": "Tony_Lainton",
            "variants": ["tony lainton", "dad", "father", "my dad",
                         "my father"],
        },
    }

    # Try to match fragment against any variant
    matched_canonical = None
    for key, info in known.items():
        for variant in info["variants"]:
            if variant in fragment or fragment in variant:
                matched_canonical = info["canonical"]
                break
        if matched_canonical:
            break

    if not matched_canonical:
        return None

    # Pull all facts about that canonical person
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT predicate, object FROM tony_facts
            WHERE subject = %s AND superseded_by IS NULL
            ORDER BY confidence DESC
        """, (matched_canonical,))
        facts = [{"predicate": r[0], "object": r[1]} for r in cur.fetchall()]
        cur.close()
        conn.close()

        return {
            "canonical_name": matched_canonical,
            "matched_on": name_fragment,
            "facts": facts,
        }
    except Exception as e:
        return {"canonical_name": matched_canonical, "matched_on": name_fragment,
                "facts": [], "error": str(e)}


def detect_people_in_text(text: str) -> List[Dict]:
    """Scan a block of text for mentions of known people."""
    if not text:
        return []
    text_lower = text.lower()
    detected = []
    seen = set()

    known_variants_to_canonical = {
        "miss wilkinson": "Georgina",
        "mrs lainton": "Georgina",
        "georgina": "Georgina",
        "wilkinson": "Georgina",
        "amelia jane": "Amelia",
        "amelia": "Amelia",
        "margot rose": "Margot",
        "margot": "Margot",
        "matthew lainton": "Matthew",
        "tony lainton": "Tony_Lainton",
    }

    for variant, canonical in known_variants_to_canonical.items():
        if variant in text_lower and canonical not in seen:
            info = resolve_name(variant)
            if info:
                detected.append({"matched": variant, **info})
                seen.add(canonical)

    return detected


def format_people_context(text: str) -> str:
    """Format people detected in text as a prompt-ready context block."""
    people = detect_people_in_text(text)
    if not people:
        return ""

    lines = ["[PEOPLE MENTIONED — relationships from memory]"]
    for p in people:
        canon = p["canonical_name"]
        matched = p["matched_on"]
        lines.append(f"  '{matched}' = {canon}")
        for f in p.get("facts", [])[:4]:
            lines.append(f"    - {f['predicate']}: {f['object']}")
    return "\n".join(lines)
