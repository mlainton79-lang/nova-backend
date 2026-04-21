---
name: photo-to-video
description: Turns Matthew's product photos into short videos suitable for Vinted, TikTok, YouTube Shorts or Instagram Reels. Use when Matthew mentions making a video, reel, short, tiktok, or wants to animate product photos he's uploaded.
version: 0.1.0
triggers:
  - make a video
  - make a reel
  - short video
  - tiktok video
  - youtube short
  - instagram reel
  - animate these photos
  - video from photos
---

# Photo-to-Video

Generate short videos from product photos using ffmpeg. Ideal for Vinted listings where a 10-15 second video massively boosts views vs a still photo.

## What you need from Matthew

- 3-8 photos of the item (or a folder path / image URLs)
- Approx length (default 10s, max 60s)
- Aspect ratio (9:16 vertical for Reels/Shorts, 1:1 square for Vinted, 16:9 landscape)
- Optional: a line of text for overlay (e.g. brand + price)

## Recommended defaults

For Vinted: 1:1 square, 12 seconds, 3 photos × 4s each, gentle Ken Burns zoom, no text overlay.
For Reels/Shorts: 9:16 vertical, 15 seconds, 5 photos × 3s each, text overlay with brand + size.

## What you CAN'T do

- Human talking-head video (need to record that yourself)
- AI-generated video (costs money — not set up)
- Voiceover (would need ElevenLabs integration — not built yet)
- Music (licensed tracks require a real music API — use Matthew's own audio file if he has one)

## What to offer if asked for something you can't do

"I can make a photo-based video now. Voiceover and music need extra setup — tell me if you want me to set that up and I'll research the cheapest path."

## Output

The endpoint `/api/v1/video/photos_to_reel` produces an mp4. Tell Matthew where the file is saved and how to download it. Keep file sizes under 20MB so it's easy to upload to Vinted/Instagram from his phone.
