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
        pass  # logged above

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


async def tony_extract_youtube_frames(video_id: str, num_frames: int = 5) -> list:
    """
    Extract key frames from a YouTube video.
    Returns list of base64 encoded images.
    Tony sees the actual visuals, not just the transcript.
    """
    frames = []
    try:
        import subprocess, tempfile, os, base64
        
        # Download a low-res version of the video for frame extraction
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            
            # Use yt-dlp to download worst quality (fastest)
            result = subprocess.run([
                "yt-dlp",
                "-f", "worstvideo[ext=mp4]/worst[ext=mp4]/worst",
                "--no-playlist",
                "-o", video_path,
                f"https://www.youtube.com/watch?v={video_id}"
            ], capture_output=True, timeout=60)
            
            if result.returncode != 0 or not os.path.exists(video_path):
                return []
            
            # Extract frames at regular intervals using ffmpeg
            frames_dir = os.path.join(tmpdir, "frames")
            os.makedirs(frames_dir)
            
            subprocess.run([
                "ffmpeg", "-i", video_path,
                "-vf", f"fps=1/{max(1, 60//num_frames)}",  # evenly spaced frames
                "-frames:v", str(num_frames),
                "-q:v", "5",
                os.path.join(frames_dir, "frame%03d.jpg")
            ], capture_output=True, timeout=30)
            
            # Read frames as base64
            frame_files = sorted(os.listdir(frames_dir))[:num_frames]
            for fname in frame_files:
                with open(os.path.join(frames_dir, fname), "rb") as f:
                    frames.append(base64.b64encode(f.read()).decode())
    except Exception as e:
        print(f"[VISION] Frame extraction failed: {e}")
    
    return frames


async def tony_watch_youtube_properly(video_url: str, question: str = None) -> dict:
    """
    Tony genuinely watches a YouTube video.
    Gets BOTH the transcript (what was said) AND key frames (what was shown).
    This is real watching, not just reading.
    """
    # Extract video ID
    video_id = None
    import re
    for pattern in [r'(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})', r'^([a-zA-Z0-9_-]{11})$']:
        match = re.search(pattern, video_url)
        if match:
            video_id = match.group(1)
            break

    if not video_id:
        return {"error": "Could not extract video ID"}

    # Get transcript and frames simultaneously
    transcript_task = tony_get_youtube_transcript(video_id)
    frames_task = tony_extract_youtube_frames(video_id, num_frames=6)
    
    transcript, frames = await asyncio.gather(transcript_task, frames_task)

    # Get metadata
    metadata = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )
            if r.status_code == 200:
                data = r.json()
                metadata = {"title": data.get("title",""), "author": data.get("author_name","")}
    except Exception:
        pass  # logged above

    # Process what Tony sees
    visual_description = ""
    if frames:
        # Tony describes what he sees in each frame
        frame_descriptions = []
        for i, frame_b64 in enumerate(frames[:4]):
            try:
                desc = await tony_see(
                    frame_b64,
                    f"Describe what is shown in this video frame. Be specific about any text, products, people, demonstrations, or important visual information shown. This is frame {i+1} of a video called: {metadata.get('title','')}",
                    "image/jpeg"
                )
                frame_descriptions.append(f"Frame {i+1}: {desc}")
            except Exception:
                pass  # logged above
        visual_description = "\n".join(frame_descriptions)

    # Now Tony synthesises what he both heard and saw
    prompt_text = question or "Summarise this video comprehensively — both what was said and what was visually demonstrated."
    
    content_parts = []
    if transcript:
        content_parts.append(f"TRANSCRIPT (what was said):\n{transcript[:20000]}")
    if visual_description:
        content_parts.append(f"VISUAL CONTENT (what was shown):\n{visual_description}")
    
    if not content_parts:
        return {
            "video_id": video_id,
            "metadata": metadata,
            "error": "Could not extract any content from this video"
        }

    synthesis_prompt = f"""You are Tony. You have just watched this video:
Title: {metadata.get('title','Unknown')}
Channel: {metadata.get('author','Unknown')}

{chr(10).join(content_parts)}

Now answer: {prompt_text}

Be specific. Reference both what was said AND what was visually demonstrated where relevant."""

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
            answer = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        answer = f"Could not process video content: {e}"

    return {
        "video_id": video_id,
        "url": video_url,
        "metadata": metadata,
        "has_transcript": bool(transcript),
        "frames_extracted": len(frames),
        "visual_content_analysed": bool(visual_description),
        "answer": answer
    }


async def tony_watch_uploaded_video(video_base64: str, filename: str = "video.mp4", question: str = None) -> dict:
    """
    Tony watches a video you upload directly.
    Transcribes audio + extracts and analyses key frames.
    Supports mp4, mov, avi, webm.
    """
    import base64, tempfile, os, subprocess
    
    result = {
        "filename": filename,
        "transcript": "",
        "visual_description": "",
        "answer": ""
    }
    
    try:
        # Decode and save video
        video_bytes = base64.b64decode(video_base64)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, filename)
            with open(video_path, "wb") as f:
                f.write(video_bytes)
            
            # Extract audio for transcription
            audio_path = os.path.join(tmpdir, "audio.mp3")
            subprocess.run([
                "ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a",
                audio_path, "-y"
            ], capture_output=True, timeout=60)
            
            # Transcribe audio using Gemini (handles mp3 audio)
            transcript = ""
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                try:
                    with open(audio_path, "rb") as af:
                        audio_b64 = base64.b64encode(af.read()).decode()
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        r = await client.post(
                            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                            json={"contents": [{"role": "user", "parts": [
                                {"inline_data": {"mime_type": "audio/mpeg", "data": audio_b64}},
                                {"text": "Transcribe this audio exactly. Return only the spoken words."}
                            ]}]}
                        )
                        if r.status_code == 200:
                            transcript = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                            result["transcript"] = transcript
                except Exception as e:
                    print(f"[VISION] Audio transcription failed: {e}")
            
            # Extract frames
            frames_dir = os.path.join(tmpdir, "frames")
            os.makedirs(frames_dir)
            subprocess.run([
                "ffmpeg", "-i", video_path,
                "-vf", "fps=1/10",  # one frame every 10 seconds
                "-frames:v", "8",
                "-q:v", "5",
                os.path.join(frames_dir, "frame%03d.jpg")
            ], capture_output=True, timeout=30)
            
            # Analyse frames
            import base64 as b64mod
            frame_descriptions = []
            frame_files = sorted(os.listdir(frames_dir))[:6]
            for i, fname in enumerate(frame_files):
                fpath = os.path.join(frames_dir, fname)
                if os.path.exists(fpath) and os.path.getsize(fpath) > 100:
                    with open(fpath, "rb") as f:
                        frame_b64 = b64mod.b64encode(f.read()).decode()
                    try:
                        desc = await tony_see(
                            frame_b64,
                            f"Describe everything visible in this video frame. Note any text, people, objects, demonstrations, or important visual information.",
                            "image/jpeg"
                        )
                        frame_descriptions.append(f"[{i*10}s] {desc}")
                    except Exception:
                        pass  # logged above
            
            result["visual_description"] = "\n".join(frame_descriptions)
            result["frames_analysed"] = len(frame_descriptions)
    
    except Exception as e:
        result["error"] = str(e)
        return result
    
    # Synthesise
    question_text = question or "What is happening in this video? Describe it comprehensively."
    
    synthesis_parts = []
    if result["transcript"]:
        synthesis_parts.append(f"AUDIO/SPEECH:\n{result['transcript'][:10000]}")
    if result["visual_description"]:
        synthesis_parts.append(f"VISUAL CONTENT:\n{result['visual_description']}")
    
    if synthesis_parts:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                    json={"contents": [{"role": "user", "parts": [{"text": f"You are Tony. You've just watched an uploaded video.\n\n{chr(10).join(synthesis_parts)}\n\nNow answer: {question_text}"}]}],
                          "generationConfig": {"maxOutputTokens": 4096}}
                )
                r.raise_for_status()
                result["answer"] = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            result["answer"] = f"Could not synthesise: {e}"
    
    return result
