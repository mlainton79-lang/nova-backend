"""
Citation Tracker — verify Tony's specific claims map to real sources.

Article's 'Glass Box' transparency pattern: users trust AI more when they
can see where information came from. Tony often says things like 'your
contract says 28 days' — if he's wrong, Matthew has no way to check.

This tracker:
  1. Detects specific claims in Tony's reply (numbers, dates, names, durations)
  2. Looks up whether those specifics are grounded in retrieved context
  3. Flags unsupported specifics
  4. Optionally generates citation markers [1] [2] linking to sources

Not an LLM call — heuristic + retrieved-context cross-check.
"""
import re
from typing import Dict, List, Optional


SPECIFIC_CLAIM_PATTERNS = [
    # Numeric claims
    (r"£\s?(\d+(?:\.\d{2})?(?:k)?)\b", "money"),
    (r"\b(\d+(?:\.\d+)?)\s?(?:%|percent)\b", "percentage"),
    (r"\b(\d{4})\b(?!\d)", "year"),
    (r"\b(\d+)\s+(?:days|weeks|months|years|hours|minutes)\b", "duration"),
    # Date patterns
    (r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|"
     r"July|August|September|October|November|December)\b", "date"),
    # Specific times
    (r"\b(\d{1,2}:\d{2})(?:\s?(?:am|pm))?\b", "time"),
]


def extract_claims(reply: str) -> List[Dict]:
    """Extract specific factual claims from a reply."""
    claims = []
    for pattern, claim_type in SPECIFIC_CLAIM_PATTERNS:
        for match in re.finditer(pattern, reply, re.IGNORECASE):
            claims.append({
                "text": match.group(0),
                "value": match.group(1) if match.groups() else match.group(0),
                "type": claim_type,
                "position": match.start(),
            })
    return claims


def verify_claims_grounded(
    reply: str,
    sources: List[Dict],
) -> Dict:
    """
    For each specific claim in the reply, check if any source contains it.
    Returns {claims, grounded_count, ungrounded_count, ungrounded_claims}.
    """
    claims = extract_claims(reply)
    if not claims:
        return {"claims": [], "grounded_count": 0, "ungrounded_count": 0,
                "ungrounded_claims": []}

    # Join all source texts for substring check
    all_source_text = " ".join(
        s.get("text", "") if isinstance(s, dict) else str(s)
        for s in sources
    ).lower()

    grounded = []
    ungrounded = []

    for claim in claims:
        # Does the exact claim text appear in any source?
        found_in_source = claim["text"].lower() in all_source_text

        # Or does the value alone appear?
        value_in_source = str(claim["value"]).lower() in all_source_text

        if found_in_source or value_in_source:
            grounded.append(claim)
        else:
            ungrounded.append(claim)

    return {
        "claims": claims,
        "grounded_count": len(grounded),
        "ungrounded_count": len(ungrounded),
        "ungrounded_claims": ungrounded,
    }


def format_citation_instruction(sources: List[Dict]) -> str:
    """
    Produce a prompt fragment listing available sources so Tony can cite
    inline. Format: '[contract:1] [nursery-letter:3] [diary:2024-04-20]'
    """
    if not sources:
        return ""

    lines = ["[AVAILABLE SOURCES for citation — refer to them briefly if used]"]
    for i, s in enumerate(sources, 1):
        src_type = s.get("source", "unknown")
        metadata = s.get("metadata", {})
        if src_type == "documents":
            name = metadata.get("doc_name", f"doc{i}")
            lines.append(f"  [{src_type}:{name}] {s.get('text', '')[:120]}")
        elif src_type == "facts":
            lines.append(f"  [fact] {s.get('text', '')[:120]}")
        elif src_type == "diary":
            date = metadata.get("date", "")
            lines.append(f"  [diary:{date}] {s.get('text', '')[:120]}")
        else:
            lines.append(f"  [{src_type}:{i}] {s.get('text', '')[:120]}")
    return "\n".join(lines)
