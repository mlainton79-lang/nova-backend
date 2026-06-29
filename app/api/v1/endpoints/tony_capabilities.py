"""Read-only Tony capability card metadata endpoints."""

from fastapi import APIRouter, Depends

from app.core.security import verify_token
from app.core.tony_capability_registry import list_tony_capability_cards

router = APIRouter()


def _capability_card_metadata(card):
    return {
        "key": card.key,
        "state": card.state,
        "title": card.title,
        "user_facing_summary": card.user_facing_summary,
        "safe_to_say": card.safe_to_say,
        "limits": list(card.limits),
    }


@router.get("/tony/capability-cards")
async def list_tony_capability_card_metadata(_=Depends(verify_token)):
    cards = [
        _capability_card_metadata(card) for card in list_tony_capability_cards()
    ]
    return {"ok": True, "count": len(cards), "cards": cards}
