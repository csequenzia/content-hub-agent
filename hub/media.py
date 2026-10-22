"""ffmpeg helpers: probe, extract audio, and render a finished vertical clip."""

import json
import shutil
import subprocess
from pathlib import Path

from . import config


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:4])} ...\n{result.stderr[-2000:]}")


def require_ffmpeg() -> None:
    for exe in ("ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            raise RuntimeError(f"{exe} is not installed (the Docker image includes it)")


def probe(video: Path) -> dict:
    """Duration, width, height of the first video stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    stream = data["streams"][0]
    return {"duration": float(data["format"]["duration"]),
            "width": int(stream["width"]), "height": int(stream["height"])}


def extract_audio(video: Path, out: Path) -> Path:
    """16 kHz mono WAV, what Whisper expects."""
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out)])
    return out


def _filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def render_clip(video: Path, start: float, end: float, ass_file: Path, out: Path,
                logo: Path | None = None) -> Path:
    """Cut [start, end], fill a 1080x1920 frame, burn captions + hook, add the logo top-right."""
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = config.OUTPUT_WIDTH, config.OUTPUT_HEIGHT
    fonts = f":fontsdir='{_filter_path(config.FONTS_DIR)}'" if config.FONTS_DIR.exists() else ""
    base = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"setsar=1,fps={config.FPS},ass='{_filter_path(ass_file)}'{fonts}")

    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(video)]
    if logo and logo.exists():
        cmd += ["-i", str(logo)]
        x = f"W-w-{config.LOGO_MARGIN}"
        graph = (f"{base}[v];[1:v]scale={config.LOGO_WIDTH}:-1[logo];"
                 f"[v][logo]overlay={x}:{config.LOGO_TOP}:format=auto[out]")
    else:
        graph = f"{base}[out]"
    cmd += ["-filter_complex", graph, "-map", "[out]", "-map", "0:a?",
            "-c:v", config.VIDEO_CODEC, "-preset", config.VIDEO_PRESET, "-crf", config.VIDEO_CRF,
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    run(cmd)
    return out
