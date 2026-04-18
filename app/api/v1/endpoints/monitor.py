"""News monitoring and weather endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.news_monitor import tony_scan_news, add_watched_topic, get_unseen_news, init_news_tables
from app.core.weather import get_weather

router = APIRouter()

@router.get("/weather")
async def weather(_=Depends(verify_token)):
    """Tony gets current weather for Rotherham."""
    return await get_weather()

@router.get("/news")
async def get_news(_=Depends(verify_token)):
    """Get unseen news items Tony has found."""
    return {"news": get_unseen_news()}

@router.post("/news/scan")
async def scan_news(_=Depends(verify_token)):
    """Tony scans all watched topics for new developments."""
    items = await tony_scan_news()
    return {"new_items": len(items), "items": items}

@router.post("/news/watch")
async def watch_topic(topic: str, keywords: str = None, _=Depends(verify_token)):
    """Tell Tony to watch a new topic."""
    ok = add_watched_topic(topic, keywords)
    return {"ok": ok}

@router.get("/news/test")
async def news_test(_=Depends(verify_token)):
    init_news_tables()
    return {"status": "News monitoring active"}
