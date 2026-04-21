"""
Tony's Skills system — modular capability bundles.

Each skill is a folder containing:
  SKILL.md — YAML frontmatter + instructions Tony loads when the skill fires
  code.py  — optional Python implementation (endpoints, helpers)
  notes.md — optional reference material (loaded only when explicitly needed)

The design mirrors Anthropic's Agent Skills pattern:
- Progressive disclosure: only the skill's name+description is in context by default
- Full body loads only when Tony determines the skill matches the current task
- Skills are portable — same structure works locally, in Railway, in the DB

Skills vs capabilities:
  capabilities/  — legacy, one-endpoint-per-file (from pre-Skills era)
  skills/        — new, bundled (code + instructions + examples + notes)

New autonomous builds go into skills/. Old capabilities continue to work.
"""
