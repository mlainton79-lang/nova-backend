"""Per-platform operator implementations.

Each operator implements the Operator protocol in base.py and is registered
in the registry below. Today's stubs all return failure paths; real
implementations land in subsequent commits.

Registry is eager (operators are instantiated at import time). This is fine
while operators have no heavy init; if any operator ever needs costly setup
(e.g., loading a credential cache), switch to lazy with a factory.
"""

from typing import Optional, Dict

from app.selling.operators.base import Operator
from app.selling.operators.ebay_stub import EbayOperator


_REGISTRY: Dict[str, Operator] = {
    "ebay": EbayOperator(),
}


def get_operator(platform: str) -> Optional[Operator]:
    """Look up the operator for a platform. Returns None if not registered."""
    return _REGISTRY.get(platform)


__all__ = ["get_operator", "Operator"]
