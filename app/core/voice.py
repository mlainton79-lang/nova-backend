"""
Tony's Voice System.

Tony speaks. Not text-to-speech from a generic engine —
Tony's voice is consistent, British, direct.

Uses Google Cloud TTS (free tier: 4 million chars/month standard, 1M WaveNet)
Falls back to gTTS (completely free, no limits) if not configured.

The voice endpoint returns base64 audio that the Android app plays.
"""
import os
import httpx
import base64
import asyncio
from typing import Optional

GOOGLE_TTS_KEY = os.environ.get("GOOGLE_TTS_KEY", "")

async def tony_speak(text: str, voice: str = "en-GB-Neural2-B") -> Optional[str]:
    """
    Convert text to speech. Returns base64 encoded MP3.
    Uses Google Cloud TTS if configured, falls back to gTTS.
    
    Voices:
    - en-GB-Neural2-B: British male (Tony's voice)
    - en-GB-Neural2-D: British male alternative
    - en-GB-Standard-B: British male standard (free tier)
    """
    # Clean text for TTS - remove markdown
    import re
    clean = re.sub(r'\*+', '', text)
    clean = re.sub(r'#{1,6}\s', '', clean)
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
    clean = re.sub(r'`[^`]+`', lambda m: m.group().replace('`',''), clean)
    clean = clean.strip()
    
    # Limit length - TTS works best with reasonable chunks
    if len(clean) > 3000:
        clean = clean[:3000] + "..."

    # Try Google Cloud TTS first (best quality)
    if GOOGLE_TTS_KEY:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_KEY}",
                    json={
                        "input": {"text": clean},
                        "voice": {
                            "languageCode": "en-GB",
                            "name": voice,
                        },
                        "audioConfig": {
                            "audioEncoding": "MP3",
                            "speakingRate": 0.95,
                            "pitch": -2.0,
                        }
                    }
                )
                if r.status_code == 200:
                    return r.json().get("audioContent")
        except Exception as e:
            print(f"[VOICE] Google TTS failed: {e}")

    # Fallback: gTTS (free, no key needed)
    try:
        import io
        from gtts import gTTS
        
        tts = gTTS(text=clean, lang='en', tld='co.uk', slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except ImportError:
        print("[VOICE] gTTS not installed - add gtts to requirements.txt")
    except Exception as e:
        print(f"[VOICE] gTTS failed: {e}")

    return None


async def tony_speak_chunked(text: str) -> list:
    """
    Split long text into speakable chunks and convert each.
    Returns list of base64 audio chunks for sequential playback.
    """
    import re
    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) < 500:
            current += " " + sentence
        else:
            if current.strip():
                chunks.append(current.strip())
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    
    # Convert chunks concurrently
    results = await asyncio.gather(*[tony_speak(chunk) for chunk in chunks[:5]])
    return [r for r in results if r]
