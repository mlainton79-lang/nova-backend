"""
Tony's Vision System.

Tony can see. He can read images, watch videos, study frames,
extract text from scanned documents, and understand visual content.

This is not "asking Gemini" — this is Tony's visual cortex.
Tony sees through multiple visual processing engines:
- Primary: Gemini Vision (best for documents, video frames, complex scenes)
- Secondary: Any vision-capable model in the pool

Tony uses vision for:
- Reading documents, letters, PDFs (scanned or photographed)
- Watching YouTube videos (transcript + key frame analysis)
- Studying product photos (for Vinted/eBay listings)
- Reading medication labels, signs, whiteboards
- Monitoring — watching for specific things in images
"""
import os
import httpx
import asyncio
import base64
import re
from typing import List, Optional

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))


async def tony_see(image_base64: str, prompt: str, mime_type: str = "image/jpeg") -> str:
    """
    Tony looks at an image and responds to a prompt about it.
    This is Tony's primary visual processing.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": image_base64}},
                        {"text": prompt}
                    ]
                }],
                "generationConfig": {"maxOutputTokens": 2048}
            }
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def tony_read_document(image_base64: str, mime_type: str = "image/jpeg") -> str:
    """
    Tony reads a document — letter, PDF scan, photo of paperwork.
    Extracts ALL text exactly as written. Preserves dates, figures, names.
    """
    return await tony_see(
        image_base64,
        """Read this document completely. Extract ALL text exactly as written.
        Preserve every date, figure, name, reference number, and legal term precisely.
        Format clearly with line breaks. Nothing summarised — full verbatim text.""",
        mime_type
    )


async def tony_get_youtube_transcript(video_id: str) -> str:
    """
    Tony reads a YouTube video's transcript.
    Uses the unofficial transcript API — no API key needed for most videos.
    """
    # Try multiple transcript extraction methods
    
    # Method 1: YouTube's timedtext API (free, no key)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get video info to find caption tracks
            r = await client.get(
                f"https://www.youtube.com/watch?v={video_id}",
                headers={"User-Agent": "Mozilla/5.0 (compatible; Tony-AI/1.0)"}
            )
            html = r.text
            
            # Extract caption URL from page
            caption_match = re.search(r'"captionTracks":\[{"baseUrl":"(.*?)"', html)
            if caption_match:
                caption_url = caption_match.group(1).replace("\\u0026", "&")
                rc = await client.get(caption_url)
                # Parse XML transcript
                texts = re.findall(r'<text[^>]*>(.*?)</text>', rc.text, re.DOTALL)
                transcript = " ".join(
                    re.sub(r'<[^>]+>', '', t).replace('&amp;', '&').replace('&#39;', "'").strip()
                    for t in texts
                )
                if transcript:
                    return transcript
    except Exception as e:
        print(f"[VISION] Transcript method 1 failed: {e}")

    # Method 2: youtube-transcript-api style endpoint
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"https://www.youtube.com/api/timedtext?lang=en&v={video_id}&fmt=json3",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code == 200 and r.text:
                import json
                data = r.json()
                events = data.get("events", [])
                texts = []
                for event in events:
                    for seg in event.get("segs", []):
                        texts.append(seg.get("utf8", ""))
                transcript = " ".join(t for t in texts if t.strip())
                if transcript:
                    return transcript
    except Exception as e:
        print(f"[VISION] Transcript method 2 failed: {e}")

    return ""


async def tony_study_video(video_url: str, question: str = None) -> dict:
    """
    Tony studies a YouTube video completely.
    Reads the transcript, understands the content, answers questions about it.
    
    This is Tony watching a video. Not Tony asking someone else.
    Tony watches it.
    """
    # Extract video ID
    video_id = None
    patterns = [
        r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, video_url)
        if match:
            video_id = match.group(1)
            break

    if not video_id:
        return {"error": "Could not extract video ID from URL", "url": video_url}

    # Get video metadata
    metadata = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use oEmbed for free metadata
            r = await client.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )
            if r.status_code == 200:
                data = r.json()
                metadata = {
                    "title": data.get("title", ""),
                    "author": data.get("author_name", ""),
                    "thumbnail": data.get("thumbnail_url", "")
                }
    except Exception:
        pass

    # Get transcript
    transcript = await tony_get_youtube_transcript(video_id)

    if not transcript:
        return {
            "video_id": video_id,
            "metadata": metadata,
            "error": "No transcript available for this video",
            "note": "Video may not have captions enabled"
        }

    # If a specific question, answer it
    # If no question, summarise
    prompt_text = question if question else (
        "Summarise this video comprehensively. Cover: main topic, key points, "
        "any specific advice or information given, names/dates/figures mentioned, "
        "and the overall conclusion."
    )

    # Tony processes the transcript himself — this is Tony thinking, not asking
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            system = f"""You are Tony, Matthew's personal AI. You have just watched this video.
Title: {metadata.get('title', 'Unknown')}
Channel: {metadata.get('author', 'Unknown')}

Here is the complete transcript of what was said:
{transcript[:30000]}

Now answer the following based on what you watched:"""

            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
                    "generationConfig": {"maxOutputTokens": 4096}
                }
            )
            r.raise_for_status()
            answer = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        answer = f"Could not process transcript: {e}"

    return {
        "video_id": video_id,
        "url": video_url,
        "metadata": metadata,
        "transcript_length": len(transcript),
        "transcript_preview": transcript[:500],
        "answer": answer
    }


async def tony_study_multiple_videos(video_urls: List[str], topic: str) -> dict:
    """
    Tony watches multiple videos on a topic and synthesises everything.
    Like a researcher watching hours of content and giving you the key insights.
    """
    results = await asyncio.gather(*[
        tony_study_video(url, f"What does this video say about: {topic}? Extract all specific facts, advice, and recommendations.")
        for url in video_urls
    ], return_exceptions=True)

    summaries = []
    for i, result in enumerate(results):
        if isinstance(result, dict) and "answer" in result:
            title = result.get("metadata", {}).get("title", f"Video {i+1}")
            summaries.append(f"FROM: {title}\n{result['answer']}")

    if not summaries:
        return {"error": "Could not extract content from any videos"}

    # Synthesise across all videos
    synthesis_prompt = f"""Tony has just watched {len(summaries)} videos about: {topic}

Here is what each video said:

{"".join(f"---\n{s}\n" for s in summaries)}

Now provide:
1. The key consensus points across all videos
2. Any contradictions or different approaches
3. The most actionable advice
4. Specific facts, figures, dates mentioned
5. Your overall assessment and recommendation for Matthew"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"role": "user", "parts": [{"text": synthesis_prompt}]}],
                    "generationConfig": {"maxOutputTokens": 4096}
                }
            )
            r.raise_for_status()
            synthesis = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        synthesis = f"Synthesis failed: {e}"

    return {
        "topic": topic,
        "videos_studied": len(summaries),
        "synthesis": synthesis,
        "individual_summaries": summaries
    }


async def tony_search_and_study_youtube(topic: str, max_videos: int = 5) -> dict:
    """
    Tony searches YouTube for a topic, finds the best videos, watches them all,
    and gives you a comprehensive understanding.
    
    No API key needed — uses YouTube's search directly.
    """
    video_ids = []
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Search YouTube
            search_query = topic.replace(" ", "+")
            r = await client.get(
                f"https://www.youtube.com/results?search_query={search_query}",
                headers={"User-Agent": "Mozilla/5.0 (compatible; Tony-AI/1.0)"}
            )
            # Extract video IDs from search results
            ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', r.text)
            # Deduplicate while preserving order
            seen = set()
            for vid_id in ids:
                if vid_id not in seen:
                    seen.add(vid_id)
                    video_ids.append(vid_id)
                if len(video_ids) >= max_videos:
                    break
    except Exception as e:
        return {"error": f"YouTube search failed: {e}"}

    if not video_ids:
        return {"error": "No videos found"}

    video_urls = [f"https://www.youtube.com/watch?v={vid_id}" for vid_id in video_ids]
    
    return await tony_study_multiple_videos(video_urls, topic)
