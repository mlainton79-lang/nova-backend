import re

INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all previous",
    r"disregard previous",
    r"forget your instructions",
    r"you are now",
    r"pretend you are",
    r"jailbreak",
]

def check_injection(message: str) -> tuple:
    lower = message.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lower):
            return True, f"Injection detected"
    return False, None
