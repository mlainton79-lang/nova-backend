"""
Video generation endpoints — ffmpeg-based.

Only generates photo-based videos for now. Voiceover, AI gen, and music are
future work.
"""
import os
import shutil
import subprocess
import tempfile
import uuid
import base64
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.security import verify_token

router = APIRouter()


def _ffmpeg_available() -> bool:
    """Check whether ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


class PhotosToReelRequest(BaseModel):
    # Photos provided either as base64 data URIs or saved file paths
    photos_base64: Optional[List[str]] = Field(default=None,
        description="Base64-encoded image data (without data:image prefix)")
    photo_paths: Optional[List[str]] = Field(default=None,
        description="Paths to saved image files on the backend")
    duration_seconds: int = Field(default=12, ge=3, le=60)
    aspect: str = Field(default="1:1",
        description="'1:1' for Vinted, '9:16' for Reels/Shorts, '16:9' for YouTube")
    text_overlay: Optional[str] = None
    ken_burns: bool = Field(default=True,
        description="Gentle zoom-in effect on each photo")


def _aspect_to_dimensions(aspect: str) -> tuple:
    """Map aspect ratio to width/height in pixels."""
    return {
        "1:1": (1080, 1080),
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
    }.get(aspect, (1080, 1080))


def _decode_photos(photos_base64: List[str], photo_paths: List[str], work_dir: Path) -> List[Path]:
    """Save all photos to work_dir and return paths in order."""
    saved = []
    if photos_base64:
        for i, b64 in enumerate(photos_base64):
            # Strip data URI prefix if present
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            data = base64.b64decode(b64)
            path = work_dir / f"photo_{i:02d}.jpg"
            path.write_bytes(data)
            saved.append(path)
    if photo_paths:
        for i, p in enumerate(photo_paths):
            src = Path(p)
            if not src.exists():
                continue
            dst = work_dir / f"photo_ext_{i:02d}{src.suffix}"
            shutil.copy(src, dst)
            saved.append(dst)
    return saved


def _build_ffmpeg_command(photos: List[Path], output_path: Path,
                         duration_sec: int, width: int, height: int,
                         ken_burns: bool, text_overlay: Optional[str]) -> List[str]:
    """Construct the ffmpeg command for a photo reel."""
    n = len(photos)
    per_photo = duration_sec / n
    fps = 30

    filter_parts = []
    for i, photo in enumerate(photos):
        # Scale + pad to target aspect, then crop
        base = (f"[{i}:v]scale={width*2}:{height*2}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}")
        if ken_burns:
            # Gentle 10% zoom over the duration of this photo
            base += (f",zoompan=z='min(zoom+0.0015,1.10)':d={int(per_photo*fps)}:"
                     f"s={width}x{height}")
        base += f",setsar=1,fps={fps}[v{i}]"
        filter_parts.append(base)

    # Concat chain
    concat_inputs = "".join(f"[v{i}]" for i in range(n))
    concat = f"{concat_inputs}concat=n={n}:v=1:a=0[concat]"
    filter_parts.append(concat)

    last_label = "concat"
    if text_overlay:
        # Escape for ffmpeg — just colons and single quotes
        safe = text_overlay.replace(":", r"\:").replace("'", r"\'")
        font_size = int(height / 18)
        filter_parts.append(
            f"[{last_label}]drawtext=text='{safe}':fontcolor=white:fontsize={font_size}:"
            f"box=1:boxcolor=black@0.6:boxborderw=20:x=(w-tw)/2:y=h-th-60[out]"
        )
        last_label = "out"

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"]
    for photo in photos:
        cmd += ["-loop", "1", "-t", f"{per_photo:.3f}", "-i", str(photo)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-preset", "medium",
        "-t", str(duration_sec),
        str(output_path),
    ]
    return cmd


@router.post("/video/photos_to_reel")
async def photos_to_reel(req: PhotosToReelRequest, _=Depends(verify_token)):
    """Generate a short video from a handful of photos."""
    if not _ffmpeg_available():
        raise HTTPException(status_code=503,
            detail="ffmpeg not installed on this Railway build. Setup task for Matthew "
                   "— add nixpacks.toml with aptPkgs=['ffmpeg'] and redeploy.")

    if not req.photos_base64 and not req.photo_paths:
        raise HTTPException(status_code=400, detail="Need photos_base64 or photo_paths")

    work_dir = Path(tempfile.mkdtemp(prefix="tony_video_"))
    try:
        photos = _decode_photos(req.photos_base64 or [], req.photo_paths or [], work_dir)
        if not photos:
            raise HTTPException(status_code=400, detail="No usable photos supplied")
        if len(photos) > 20:
            raise HTTPException(status_code=400, detail="Max 20 photos per reel")

        width, height = _aspect_to_dimensions(req.aspect)
        output_path = work_dir / f"reel_{uuid.uuid4().hex[:8]}.mp4"

        cmd = _build_ffmpeg_command(
            photos, output_path, req.duration_seconds,
            width, height, req.ken_burns, req.text_overlay
        )

        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise HTTPException(status_code=500,
                detail=f"ffmpeg failed: {proc.stderr.decode()[-800:]}")

        # Save to a persistent location so Matthew can download
        persistent_dir = Path("/tmp/tony_videos")
        persistent_dir.mkdir(exist_ok=True)
        final_path = persistent_dir / output_path.name
        shutil.move(output_path, final_path)

        return {
            "ok": True,
            "video_path": str(final_path),
            "filename": final_path.name,
            "size_bytes": final_path.stat().st_size,
            "duration_seconds": req.duration_seconds,
            "aspect": req.aspect,
            "note": "Video saved on backend. Use /video/download/{filename} to fetch.",
        }
    finally:
        # Clean up temp dir (but keep the final video)
        try:
            for p in work_dir.iterdir():
                if p.suffix != ".mp4":
                    try: p.unlink()
                    except Exception: pass
        except Exception:
            pass


@router.get("/video/download/{filename}")
async def download_video(filename: str, _=Depends(verify_token)):
    """Download a generated video."""
    from fastapi.responses import FileResponse
    path = Path("/tmp/tony_videos") / filename
    if not path.exists() or ".." in filename:
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/video/list")
async def list_videos(_=Depends(verify_token)):
    """List recently-generated videos."""
    d = Path("/tmp/tony_videos")
    if not d.exists():
        return {"ok": True, "videos": []}
    videos = sorted(d.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "ok": True,
        "videos": [
            {"filename": v.name, "size_bytes": v.stat().st_size,
             "created_ts": int(v.stat().st_mtime)}
            for v in videos[:20]
        ],
    }


@router.get("/video/health")
async def video_health(_=Depends(verify_token)):
    """Check whether video generation is available."""
    return {
        "ok": True,
        "ffmpeg_available": _ffmpeg_available(),
        "ffmpeg_version": subprocess.run(
            ["ffmpeg", "-version"], capture_output=True
        ).stdout.decode().split("\n")[0] if _ffmpeg_available() else None,
    }
