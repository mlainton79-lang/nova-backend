import os

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEV_TOKEN = os.environ.get("DEV_TOKEN", "nova-dev-token")

# N1.5-A: Capability Builder safe mode gates (default false).
# - STAGING_ENABLED gates ALL staging including manual /builder/build.
# - AUTONOMOUS_STAGING_ENABLED gates chat-driven autonomous staging via gap_detector.
# Both default false. Set to "true" in Railway env vars to enable.
# Why: prevents 5 LLM calls + 2 Brave queries firing without explicit operator opt-in
# while exec_module removal (N1.5-B), filename allow-list (N1.5-C), staging budget
# guard (N1.5-D), branch/PR push (N1.5-E), and audit log (N1.5-F) are still pending.
CAPABILITY_BUILDER_STAGING_ENABLED = os.environ.get("CAPABILITY_BUILDER_STAGING_ENABLED", "false").lower() == "true"
CAPABILITY_BUILDER_AUTONOMOUS_STAGING_ENABLED = os.environ.get("CAPABILITY_BUILDER_AUTONOMOUS_STAGING_ENABLED", "false").lower() == "true"
