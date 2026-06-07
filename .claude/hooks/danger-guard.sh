#!/usr/bin/env bash
# PreToolUse danger-guard for Nova. Blocks unambiguously dangerous git ops
# on this shared clone. Exit 2 = block (reason to stderr); exit 0 = allow.
# Reads CC's PreToolUse JSON on stdin; inspects tool_input.command.

cmd="$(jq -r '.tool_input.command // empty' 2>/dev/null)"

# Nothing to inspect -> allow (don't block on parse failure of a non-Bash call).
[ -z "$cmd" ] && exit 0

# --- Guard 1: force-push (every spelling) ---
if printf '%s' "$cmd" | grep -Eq 'git[[:space:]]+push([[:space:]]+[^|;&]*)?([[:space:]]+(-f|--force|--force-with-lease))([[:space:]]|$|=)'; then
    echo "BLOCKED: force-push is forbidden on this shared clone (GIT-SAFETY rule). Use a merge, or push without --force." >&2
    exit 2
fi

# --- Guard 2: hard reset ---
if printf '%s' "$cmd" | grep -Eq 'git[[:space:]]+reset([[:space:]]+[^|;&]*)?[[:space:]]+--hard'; then
    echo "BLOCKED: 'git reset --hard' is forbidden on this shared clone (GIT-SAFETY rule). It discards committed work irrecoverably." >&2
    exit 2
fi

exit 0
