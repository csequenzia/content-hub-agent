"""Turn an edit plan into a first-draft folder: the rendered Reel plus a post.json.

This part needs no API key, so it can be tested on its own with a hand-written plan.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import captions, config, media
from .brand import load_brand, logo_path


def snap_to_words(transcript: dict, start: float, end: float) -> tuple[float, float]:
    """Move start/end out to the nearest word edges so a cut never lands mid-word."""
    words = [w for s in transcript["segments"] for w in s.get("words", [])]
    if not words:
        return start, end
    before = [w["start"] for w in words if w["start"] <= start + 0.25]
    after = [w["end"] for w in words if w["end"] >= end - 0.25]
    new_start = max(before) if before else words[0]["start"]
    new_end = min(after) if after else words[-1]["end"]
    # A little air before the first word and after the last
    return max(0.0, new_start - 0.1), min(transcript["duration"], new_end + 0.3)


def folder_name(stem: str) -> str:
    """The video's name made safe for ffmpeg's filter syntax, which breaks on ' , : [ ] and friends.

    The captions file lives in this folder and goes inside an ffmpeg filter, so a video called
    "I've coached 7,000 Christians.mp4" would otherwise fail to render.
    """
    return re.sub(r"[^A-Za-z0-9 _-]+", "", stem).strip() or "video"


def validate_plan(plan: dict, transcript: dict) -> list[str]:
    problems = []
    for key in ("start", "end", "hook", "post_caption"):
        if key not in plan:
            problems.append(f"missing '{key}'")
    if problems:
        return problems
    length = plan["end"] - plan["start"]
    if plan["start"] < 0 or plan["end"] > transcript["duration"] + 0.5:
        problems.append(f"times must be inside the video (0-{transcript['duration']:.1f}s)")
    short_video = transcript["duration"] < config.MIN_CLIP_SECONDS
    if not short_video and not (config.MIN_CLIP_SECONDS - 2 <= length <= config.MAX_CLIP_SECONDS + 2):
        problems.append(f"clip is {length:.1f}s; it must be {config.MIN_CLIP_SECONDS}-{config.MAX_CLIP_SECONDS}s")
    if len(plan["hook"]) > 70:
        problems.append("hook is too long for the screen; keep it under 70 characters")
    return problems


def render_draft(video: Path, client_id: str, transcript: dict, plan: dict,
                 drafts_dir: Path = config.DRAFTS_DIR) -> Path:
    problems = validate_plan(plan, transcript)
    if problems:
        raise ValueError("; ".join(problems))
    brand = load_brand(client_id)
    start, end = snap_to_words(transcript, plan["start"], plan["end"])

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = drafts_dir / client_id / f"{folder_name(video.stem)}-{stamp}"
    words = captions.words_in_range(transcript, start, end)
    ass = captions.write_ass(captions.chunk_words(words), plan["hook"], brand, folder / "captions.ass")
    out = media.render_clip(video, start, end, ass, folder / f"{video.stem} - first draft.mp4",
                            logo=logo_path(client_id, brand))

    post = {
        "client": client_id,
        "source_video": video.name,
        "clip_start": round(start, 2),
        "clip_end": round(end, 2),
        "hook": plan["hook"],
        "post_caption": plan["post_caption"],
        "hashtags": plan.get("hashtags", []),
        "why_this_clip": plan.get("why", ""),
        "status": "needs_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "post.json").write_text(json.dumps(post, indent=2))
    return out
