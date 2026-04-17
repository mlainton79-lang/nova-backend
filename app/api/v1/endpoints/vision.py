"""
Tony's Vision endpoints.
Tony watches videos, reads documents, studies images.
This is Tony's capability — not a third party service.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.vision import (
    tony_study_video,
    tony_study_multiple_videos,
    tony_search_and_study_youtube,
    tony_see,
    tony_read_document
)

router = APIRouter()

@router.post("/vision/watch")
async def watch_video(url: str, question: str = None, _=Depends(verify_token)):
    """Tony watches a YouTube video and answers questions about it."""
    return await tony_study_video(url, question)

@router.post("/vision/research")
async def research_topic(topic: str, max_videos: int = 5, _=Depends(verify_token)):
    """Tony searches YouTube, watches the top videos on a topic, synthesises everything."""
    return await tony_search_and_study_youtube(topic, max_videos)

@router.post("/vision/watch-multiple")
async def watch_multiple(urls: list, topic: str, _=Depends(verify_token)):
    """Tony watches multiple specific videos and synthesises them."""
    return await tony_study_multiple_videos(urls, topic)

@router.post("/vision/see")
async def see_image(image_base64: str, prompt: str, mime_type: str = "image/jpeg", _=Depends(verify_token)):
    """Tony looks at an image and responds to a prompt about it."""
    result = await tony_see(image_base64, prompt, mime_type)
    return {"result": result}

@router.post("/vision/read-document")
async def read_document(image_base64: str, mime_type: str = "image/jpeg", _=Depends(verify_token)):
    """Tony reads a document image and extracts all text verbatim."""
    result = await tony_read_document(image_base64, mime_type)
    return {"text": result}

@router.get("/vision/test")
async def vision_test(_=Depends(verify_token)):
    """Test Tony's vision system."""
    return {
        "status": "Tony's vision system is active",
        "capabilities": [
            "watch YouTube videos",
            "research topics by watching multiple videos",
            "read documents and extract text",
            "analyse images",
            "search YouTube and study results"
        ]
    }
