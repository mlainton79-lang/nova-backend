"""Read-only MCP-style tool surface for Nova.

This is deliberately a small HTTP/JSON-RPC compatible layer, not a full
transport implementation. It exposes safe read-only Nova state to future MCP
clients without granting write tools or bypassing the approval lock.
"""

from typing import Any, Awaitable, Callable, Dict


ToolHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


def _tool_schema(name: str, description: str, properties: Dict[str, Any] | None = None):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "additionalProperties": False,
        },
    }


async def _today_brief(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.today_brief import get_today_brief

    return await get_today_brief()


async def _daily_review(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.daily_review import get_daily_review

    return await get_daily_review()


async def _capability_cards(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.tony_capability_registry import list_tony_capability_cards

    cards = [
        {
            "key": card.key,
            "state": card.state,
            "title": card.title,
            "user_facing_summary": card.user_facing_summary,
            "safe_to_say": card.safe_to_say,
            "limits": list(card.limits),
        }
        for card in list_tony_capability_cards()
    ]
    return {"ok": True, "count": len(cards), "cards": cards}


async def _codebase_stats(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.codebase_sync import get_codebase_stats

    return {"ok": True, "stats": get_codebase_stats()}


async def _daily_loop_quality(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.capture import capture_note
    from app.core.daily_loop_quality import (
        combine_daily_loop_quality,
        evaluate_capture_result,
        evaluate_daily_review_payload,
        evaluate_today_brief_payload,
    )
    from app.core.daily_review import get_daily_review
    from app.core.today_brief import get_today_brief

    return combine_daily_loop_quality([
        evaluate_today_brief_payload(await get_today_brief()),
        evaluate_daily_review_payload(await get_daily_review()),
        evaluate_capture_result(await capture_note("api key should not be saved")),
    ])


async def _daily_surface_model_eval(_arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.daily_surface_model_eval import run_daily_surface_model_eval

    return await run_daily_surface_model_eval()


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


async def _failure_candidates(arguments: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.production_failure_evals import recent_failure_events

    minutes = _bounded_int(arguments.get("minutes"), default=24 * 60, minimum=1, maximum=24 * 60)
    limit = _bounded_int(arguments.get("limit"), default=25, minimum=1, maximum=100)
    return recent_failure_events(minutes=minutes, limit=limit)


TOOL_DEFINITIONS = (
    _tool_schema("nova.today_brief", "Read Nova's actionable Today Brief."),
    _tool_schema("nova.daily_review", "Read Nova's end-of-day Daily Review."),
    _tool_schema("nova.capability_cards", "List Nova capability truth cards."),
    _tool_schema("nova.codebase_stats", "Read codebase sync statistics."),
    _tool_schema("nova.daily_loop_quality", "Run deterministic daily-loop quality checks."),
    _tool_schema("nova.daily_surface_model_eval", "Run model-assisted Today Brief / Daily Review quality checks."),
    _tool_schema(
        "nova.failure_candidates",
        "Suggest eval cases from recent production warning/error/critical events.",
        properties={
            "minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    ),
)


TOOL_HANDLERS: Dict[str, ToolHandler] = {
    "nova.today_brief": _today_brief,
    "nova.daily_review": _daily_review,
    "nova.capability_cards": _capability_cards,
    "nova.codebase_stats": _codebase_stats,
    "nova.daily_loop_quality": _daily_loop_quality,
    "nova.daily_surface_model_eval": _daily_surface_model_eval,
    "nova.failure_candidates": _failure_candidates,
}


def list_tools() -> Dict[str, Any]:
    return {"tools": list(TOOL_DEFINITIONS)}


async def call_tool(name: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        }
    result = await handler(arguments or {})
    return {
        "content": [{"type": "json", "json": result}],
        "isError": False,
    }


async def handle_jsonrpc(payload: Dict[str, Any]) -> Dict[str, Any]:
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "tools/list":
        result = list_tools()
    elif method == "tools/call":
        result = await call_tool(
            str(params.get("name") or ""),
            params.get("arguments") if isinstance(params.get("arguments"), dict) else {},
        )
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    return {"jsonrpc": "2.0", "id": request_id, "result": result}
