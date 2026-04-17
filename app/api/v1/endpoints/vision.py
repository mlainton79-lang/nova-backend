"""
Tony's Vision endpoints.
Tony watches videos, reads documents, studies images.
Tony watches — not Gemini, not a third party. Tony.
"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.vision import (
    tony_study_video,
    tony_watch_youtube_properly,
    tony_study_multiple_videos,
    tony_search_and_study_youtube,
    tony_watch_uploaded_video,
    tony_see,
    tony_read_document
)

router = APIRouter()

@router.post("/vision/watch")
async def watch_video(url: str, question: str = None, full: bool = True, _=Depends(verify_token)):
    """
    Tony watches a YouTube video.
    full=True: extracts transcript AND visual frames (what was said + what was shown)
    full=False: transcript only (faster)
    """
    if full:
        return await tony_watch_youtube_properly(url, question)
    return await tony_study_video(url, question)

@router.post("/vision/upload")
async def watch_uploaded_video(
    question: str = None,
    video_url: str = None,
    _=Depends(verify_token)
):
    """
    Tony watches an uploaded video by URL or base64.
    For direct file upload, send base64 encoded video as video_url param.
    """
    if not video_url:
        return {"error": "Provide video as base64 in video_url parameter"}
    import base64 as b64
    return await tony_watch_uploaded_video(video_url, "video.mp4", question)

@router.post("/vision/research")
async def research_topic(topic: str, max_videos: int = 5, _=Depends(verify_token)):
    """Tony searches YouTube, watches the top videos, synthesises everything."""
    return await tony_search_and_study_youtube(topic, max_videos)

@router.post("/vision/watch-multiple")
async def watch_multiple(urls_csv: str, topic: str, _=Depends(verify_token)):
    """Tony watches multiple specific videos (comma-separated URLs) and synthesises them."""
    urls = [u.strip() for u in urls_csv.split(",") if u.strip()]
    return await tony_study_multiple_videos(urls, topic)

@router.post("/vision/see")
async def see_image(image_base64: str, prompt: str, mime_type: str = "image/jpeg", _=Depends(verify_token)):
    """Tony looks at an image."""
    result = await tony_see(image_base64, prompt, mime_type)
    return {"result": result}

@router.post("/vision/read-document")
async def read_document(image_base64: str, mime_type: str = "image/jpeg", _=Depends(verify_token)):
    """Tony reads a document — scanned letter, photo of paperwork — extracts all text verbatim."""
    result = await tony_read_document(image_base64, mime_type)
    return {"text": result}

@router.get("/vision/test")
async def vision_test(_=Depends(verify_token)):
    return {
        "status": "Tony's vision is active",
        "watching": {
            "youtube_transcript": "reads what was said",
            "youtube_frames": "sees what was shown",
            "uploaded_video": "watches your own videos - audio transcription + visual frames",
            "images": "sees and analyses any image",
            "documents": "reads scanned letters, PDFs, photos of paperwork verbatim"
        },
        "note": "Tony watches. Tony sees. This is Tony's capability."
    }
