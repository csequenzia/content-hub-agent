"""Turn an edit plan into a first-draft folder: the rendered Reel plus a post.json.

This part needs no API key, so it can be tested on its own with a hand-written plan.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config, looks, media, recipes, timeline
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


def plan_segments(plan: dict) -> list[tuple[float, float]]:
    """The stretches of raw video Claude chose: `segments`, or one `start`-`end` stretch."""
    if plan.get("segments"):
        return [(float(x["start"]), float(x["end"])) for x in plan["segments"]]
    if "start" in plan and "end" in plan:
        return [(float(plan["start"]), float(plan["end"]))]
    return []


def validate_plan(plan: dict, transcript: dict, recipe: dict | None = None) -> list[str]:
    recipe = recipe or recipes.load_recipe(None)
    lo, hi = recipe["length"]["min"], recipe["length"]["max"]
    problems = [f"missing '{key}'" for key in ("hook", "post_caption") if key not in plan]
    segments = plan_segments(plan)
    if not segments:
        problems.append("missing 'segments' (or 'start' and 'end')")
    if problems:
        return problems
    if any(s < 0 or e > transcript["duration"] + 0.5 or e <= s for s, e in segments):
        problems.append(f"times must be inside the video (0-{transcript['duration']:.1f}s), each end after its start")
    length = timeline.length(timeline.merge(segments))
    short_video = transcript["duration"] < lo
    if not short_video and not (lo - 2 <= length <= hi + 2):
        problems.append(f"clip is {length:.1f}s; it must be {lo}-{hi}s")
    hook_lines = plan.get("hook_lines") or [plan["hook"]]
    if len(hook_lines[0]) > 70:
        problems.append("hook is too long for the screen; keep it under 70 characters")
    for shot in plan.get("shots") or []:
        if not 1.0 <= float(shot.get("zoom", 1)) <= 2.0:
            problems.append("each shot's zoom must be between 1.0 (full frame) and 2.0")
            break
    return problems


def default_shots(recipe: dict, segments: list[tuple[float, float]]) -> list[dict]:
    """The recipe's camera plan (fractions of the Reel) turned into raw-video times."""
    total = timeline.length(segments)
    out = []
    for shot in recipe.get("shots") or []:
        reel_t, acc = shot["at"] * total, 0.0
        for s, e in segments:
            if acc + (e - s) >= reel_t:
                out.append({"at": s + (reel_t - acc), "zoom": shot["zoom"]})
                break
            acc += e - s
    return out


def render_draft(video: Path, client_id: str, transcript: dict, plan: dict,
                 drafts_dir: Path = config.DRAFTS_DIR, recipe: dict | None = None) -> Path:
    recipe = recipe or recipes.load_recipe(None)
    problems = validate_plan(plan, transcript, recipe)
    if problems:
        raise ValueError("; ".join(problems))
    brand = load_brand(client_id)
    segments = timeline.snap(transcript, plan_segments(plan))
    segments = timeline.cut_pauses(transcript, segments, recipe["pauses"].get("max_gap"))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = drafts_dir / client_id / f"{folder_name(video.stem)}-{stamp}"
    words = timeline.reel_words(transcript, segments)
    hook_lines = [x for x in (plan.get("hook_lines") or [plan["hook"]]) if x.strip()]
    ass = looks.write_captions(words, recipe, brand, folder / "captions.ass",
                               hook_text=" ".join(hook_lines), emphasis=plan.get("emphasis"))
    overlays = []
    if recipe["hook"].get("look") == "boxes" and hook_lines:
        png = looks.hook_boxes_png(hook_lines, recipe, folder / "hook.png")
        overlays.append((png, 0.0, looks.hook_until(recipe, words)))

    raw_shots = plan.get("shots") or default_shots(recipe, segments)
    shots = []
    for shot in raw_shots:
        at = timeline.to_reel(segments, float(shot["at"]))
        if at is None:   # the shot starts inside a cut: begin it where the Reel resumes
            later = [s for s, _ in segments if s >= float(shot["at"])]
            at = timeline.to_reel(segments, later[0]) if later else None
        if at is not None:
            shots.append({"at": at, "zoom": float(shot["zoom"])})
    out = media.render_edit(video, segments, ass, folder / f"{video.stem} - first draft.mp4",
                            shots=shots, focus=plan.get("focus") or recipe.get("focus"), overlays=overlays)

    post = {
        "client": client_id,
        "source_video": video.name,
        "recipe": recipe.get("template"),
        "segments": [[round(s, 2), round(e, 2)] for s, e in segments],
        "clip_start": round(segments[0][0], 2),
        "clip_end": round(segments[-1][1], 2),
        "hook": plan["hook"],
        "post_caption": plan["post_caption"],
        "hashtags": plan.get("hashtags", []),
        "why_this_clip": plan.get("why", ""),
        "status": "needs_review",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "post.json").write_text(json.dumps(post, indent=2))
    return out
