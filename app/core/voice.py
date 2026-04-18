"""
Tony's Voice System.

Priority order:
1. Azure Cognitive Services TTS — 500k chars/month free, natural British male
2. Google Cloud TTS — if key is set
3. gTTS — robotic fallback, always works, no key needed

Returns base64 MP3. Android app decodes and plays it.
"""
import os
import re
import httpx
import base64
import asyncio
from typing import Optional

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# Daniel voice - natural British male
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "uksouth")
GOOGLE_TTS_KEY = os.environ.get("GOOGLE_TTS_KEY", "")
AZURE_VOICE = os.environ.get("AZURE_VOICE", "en-GB-RyanNeural")


def _clean_text(text: str) -> str:
    clean = re.sub(r'\*+', '', text)
    clean = re.sub(r'#{1,6}\s', '', clean)
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
    clean = re.sub(r'`[^`]+`', lambda m: m.group().replace('`', ''), clean)
    clean = re.sub(r'\n+', ' ', clean)
    clean = clean.strip()
    if len(clean) > 2500:
        clean = clean[:2500] + "..."
    return clean


async def _elevenlabs_speak(text: str) -> Optional[str]:
    """ElevenLabs TTS — genuinely natural voice, best quality."""
    if not ELEVENLABS_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg"
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "style": 0.3,
                        "use_speaker_boost": True
                    }
                }
            )
            if r.status_code == 200:
                return base64.b64encode(r.content).decode()
            else:
                print(f"[VOICE] ElevenLabs error {r.status_code}: {r.text[:200]}")
                return None
    except Exception as e:
        print(f"[VOICE] ElevenLabs failed: {e}")
        return None


async def _azure_speak(text: str) -> Optional[str]:
    """Azure Cognitive Services TTS — 500k chars/month free."""
    if not AZURE_SPEECH_KEY:
        return None
    try:
        ssml = f"""<speak version='1.0' xml:lang='en-GB'>
            <voice name='{AZURE_VOICE}'>
                <prosody rate='0%' pitch='-5%'>{text}</prosody>
            </voice>
        </speak>"""

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
                headers={
                    "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-48khz-96kbitrate-mono-mp3",
                    "User-Agent": "TonyAI"
                },
                content=ssml.encode("utf-8")
            )
            if r.status_code == 200:
                return base64.b64encode(r.content).decode()
            else:
                print(f"[VOICE] Azure error {r.status_code}: {r.text[:200]}")
                return None
    except Exception as e:
        print(f"[VOICE] Azure failed: {e}")
        return None


async def _google_speak(text: str, voice: str = "en-GB-Neural2-B") -> Optional[str]:
    if not GOOGLE_TTS_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_KEY}",
                json={
                    "input": {"text": text},
                    "voice": {"languageCode": "en-GB", "name": voice},
                    "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.95, "pitch": -2.0}
                }
            )
            if r.status_code == 200:
                return r.json().get("audioContent")
    except Exception as e:
        print(f"[VOICE] Google TTS failed: {e}")
    return None


async def _gtts_speak(text: str) -> Optional[str]:
    try:
        import io
        from gtts import gTTS
        tts = gTTS(text=text, lang='en', tld='co.uk', slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as e:
        print(f"[VOICE] gTTS failed: {e}")
        return None


async def tony_speak(text: str, voice: str = "en-GB-RyanNeural") -> Optional[str]:
    clean = _clean_text(text)
    if not clean:
        return None

    # 1. ElevenLabs — best quality, most natural
    result = await _elevenlabs_speak(clean)
    if result:
        print("[VOICE] ElevenLabs OK")
        return result

    # 2. Azure — good quality, 500k chars/month free
    result = await _azure_speak(clean)
    if result:
        print("[VOICE] Azure TTS OK")
        return result

    # 3. Google Cloud TTS
    result = await _google_speak(clean, voice)
    if result:
        print("[VOICE] Google TTS OK")
        return result

    # 4. gTTS fallback
    print("[VOICE] Falling back to gTTS")
    return await _gtts_speak(clean)


async def tony_speak_chunked(text: str) -> list:
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
    results = await asyncio.gather(*[tony_speak(chunk) for chunk in chunks[:5]])
    return [r for r in results if r]
