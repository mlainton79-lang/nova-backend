"""
Artifact Extractor — identify and separate artifacts from chat responses.

The article describes the 'Canvas' pattern: chat on one side, result on the 
other. For Matthew's Android app to support this eventually, the backend 
needs to identify when a reply contains an artifact (vs conversational text).

Examples of artifacts:
  - A drafted email (3+ paragraphs, recipient implied)
  - A code snippet (```language...```)
  - A structured list (numbered checklist, shopping list, itinerary)
  - A document (100+ word structured text with headers)
  - A recipe
  - A formatted table (markdown pipes)
  - A long-form piece (review, analysis, report)

This doesn't REMOVE the artifact from the reply — it adds a structured 
artifacts[] field alongside the reply. The Android app can choose to render 
either. Zero breakage of existing clients.
"""
import re
from typing import Dict, List


# Language hints for code blocks
CODE_LANGUAGES = {
    "python", "javascript", "js", "typescript", "ts",
    "kotlin", "java", "swift", "go", "rust", "c", "cpp",
    "bash", "shell", "sh", "sql", "html", "css", "json",
    "yaml", "toml", "xml", "dockerfile", "ruby", "php",
}


def _extract_code_blocks(text: str) -> List[Dict]:
    """Extract all ```lang...``` blocks."""
    artifacts = []
    pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(text):
        lang = (match.group(1) or "").lower() or "text"
        code = match.group(2)
        if len(code.strip()) < 5:
            continue
        artifacts.append({
            "type": "code",
            "language": lang,
            "content": code,
            "title": f"{lang or 'code'} snippet",
        })
    return artifacts


def _extract_markdown_table(text: str) -> List[Dict]:
    """Detect markdown tables (| col | col |)."""
    artifacts = []
    # Simple heuristic: 3+ lines where each has at least 2 pipes
    lines = text.split("\n")
    current_table = []
    for line in lines:
        if line.count("|") >= 2 and "---" not in line:
            current_table.append(line)
        elif "---" in line and line.count("|") >= 2:
            current_table.append(line)
        else:
            if len(current_table) >= 3:
                artifacts.append({
                    "type": "table",
                    "content": "\n".join(current_table),
                    "title": "table",
                })
            current_table = []
    if len(current_table) >= 3:
        artifacts.append({
            "type": "table",
            "content": "\n".join(current_table),
            "title": "table",
        })
    return artifacts


def _extract_list(text: str) -> List[Dict]:
    """Detect structured lists (numbered or bulleted, 4+ items)."""
    artifacts = []
    lines = text.split("\n")
    current = []
    list_type = None
    for line in lines:
        stripped = line.strip()
        # Numbered list
        if re.match(r"^\d+[\.\)]\s+", stripped):
            if list_type != "numbered":
                if len(current) >= 4:
                    artifacts.append({
                        "type": "list",
                        "list_type": list_type,
                        "content": "\n".join(current),
                        "title": f"{list_type or ''} list",
                    })
                current = []
                list_type = "numbered"
            current.append(stripped)
        # Bullet list
        elif re.match(r"^[\-\*]\s+", stripped):
            if list_type != "bulleted":
                if len(current) >= 4:
                    artifacts.append({
                        "type": "list",
                        "list_type": list_type,
                        "content": "\n".join(current),
                        "title": f"{list_type or ''} list",
                    })
                current = []
                list_type = "bulleted"
            current.append(stripped)
        else:
            if len(current) >= 4:
                artifacts.append({
                    "type": "list",
                    "list_type": list_type,
                    "content": "\n".join(current),
                    "title": f"{list_type or ''} list",
                })
            current = []
            list_type = None
    if len(current) >= 4:
        artifacts.append({
            "type": "list",
            "list_type": list_type,
            "content": "\n".join(current),
            "title": f"{list_type or ''} list",
        })
    return artifacts


def _detect_email_draft(text: str, user_message: str) -> List[Dict]:
    """Detect if the reply is an email draft."""
    # Heuristic: user asked about email/reply/draft AND reply has email-like structure
    asked_for_email = bool(re.search(
        r"\b(email|reply|respond|draft|write back|send to)\b",
        user_message.lower()
    ))
    if not asked_for_email:
        return []

    # Email-like structure: has greeting + body + sign-off OR clear paragraph structure
    has_greeting = bool(re.search(
        r"\b(dear|hi|hello|hey)\s+[A-Z][a-z]+", text, re.IGNORECASE
    ))
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    has_multiple_paragraphs = len(paragraphs) >= 2
    is_substantial = len(text.split()) > 10

    if has_greeting and has_multiple_paragraphs and is_substantial:
        return [{
            "type": "email_draft",
            "content": text.strip(),
            "title": "Email draft",
        }]
    # OR if it's a substantial reply and email was explicitly asked for
    if has_multiple_paragraphs and is_substantial:
        return [{
            "type": "email_draft",
            "content": text.strip(),
            "title": "Draft message",
        }]
    return []


def extract_artifacts(reply: str, user_message: str = "") -> List[Dict]:
    """Main entry. Returns list of detected artifacts in reply."""
    if not reply or len(reply) < 20:
        return []

    artifacts = []
    artifacts.extend(_extract_code_blocks(reply))
    artifacts.extend(_extract_markdown_table(reply))

    # Only detect list if no code/table (they overlap)
    if not artifacts:
        artifacts.extend(_extract_list(reply))

    # Email draft detection needs user context
    if user_message:
        artifacts.extend(_detect_email_draft(reply, user_message))

    return artifacts


def has_canvas_worthy_content(reply: str, user_message: str = "") -> bool:
    """Quick check: does this reply have anything worth rendering in a canvas?"""
    return bool(extract_artifacts(reply, user_message))
