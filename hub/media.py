"""ffmpeg helpers: probe, extract audio, and render a finished vertical clip."""

import json
import re
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


def has_stream(video: Path, kind: str = "a") -> bool:
    """Whether the file has an audio ("a") or video ("v") stream."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout
    return bool(out.strip())


def duration(video: Path) -> float:
    """Seconds, read by decoding when the header has none (browser-recorded WebM)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        log = subprocess.run(["ffmpeg", "-v", "info", "-i", str(video), "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        stamps = re.findall(r"time=(\d+):(\d+):([\d.]+)", log)
        h, m, sec = stamps[-1] if stamps else (0, 0, 0)
        return int(h) * 3600 + int(m) * 60 + float(sec)


def join_clips(clips: list[Path], out: Path) -> Path:
    """Join clips end to end into one video (several teleprompter takes become one raw video).

    Clips can differ in size, frame rate or camera (front/back), so each is brought to the
    Reel frame first. A single clip goes through the same step, which also turns browser
    WebM (no duration in its header) into a normal MP4.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = config.OUTPUT_WIDTH, config.OUTPUT_HEIGHT
    cmd, parts, labels = ["ffmpeg", "-y", "-v", "error"], [], ""
    for i, clip in enumerate(clips):
        if not has_stream(clip, "v"):
            raise RuntimeError(f"Clip {i + 1} has no picture (the browser recorded sound only). Film it again.")
        cmd += ["-i", str(clip)]
    silent = len(clips)
    for i, clip in enumerate(clips):
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                     f"setsar=1,fps={config.FPS},format=yuv420p[v{i}]")
        if has_stream(clip, "a"):
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:   # a clip with no sound gets silence of its own length
            cmd += ["-f", "lavfi", "-t", f"{duration(clip):.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            parts.append(f"[{silent}:a]anull[a{i}]")
            silent += 1
        labels += f"[v{i}][a{i}]"
    parts.append(f"{labels}concat=n={len(clips)}:v=1:a=1[v][a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
            "-c:v", config.VIDEO_CODEC, "-preset", config.VIDEO_PRESET, "-crf", "17",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    run(cmd)
    return out


def extract_audio(video: Path, out: Path) -> Path:
    """16 kHz mono WAV, what Whisper expects."""
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
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
