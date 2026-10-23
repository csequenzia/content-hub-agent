"""Course lesson mode: the steps of Katrina's edit-course-lesson skill that don't need judgment.

The skill (in .claude/skills/edit-course-lesson/) is a HyperFrames kit: Node scripts cut
the video and turn lesson-plan.json into an animated page, and HyperFrames renders that
page with Chrome. This module runs those scripts. Claude does the judgment parts (which
mistakes to cut, the lesson plan, the image prompts) through the tools in agent.py.

One lesson = one project folder: drafts/<client>/<video>-<stamp>/
  assets/raw.mp4            copy of the upload
  assets/raw.json           word transcript (kit format)
  assets/silenced.mp4       after cut-silences
  assets/clean.mp4          after the approved mistake cuts (if any)
  assets/transcript.json    transcript that matches the final video
  assets/aids/*.png         Higgsfield images
  lesson-plan.json          Claude's plan; index.html + lesson-timing.md are built from it
  renders/draft.mp4         the finished draft
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .transcribe import transcribe

SKILLS = config.ROOT / ".claude" / "skills"
BUILD = SKILLS / "edit-course-lesson" / "scripts" / "build-lesson.mjs"
CUT_SILENCES = SKILLS / "cut-silences" / "scripts" / "cut-silences.mjs"
FIND_CUTS = SKILLS / "cut-mistakes" / "scripts" / "find-cut-candidates.mjs"
APPLY_CUTS = SKILLS / "cut-mistakes" / "scripts" / "apply-cuts.mjs"
STARTER = config.ROOT / "course" / "starter"
PREFLIGHT = config.ROOT / "course" / "preflight.mjs"
NODE_BIN = config.ROOT / "node_modules" / ".bin"
GSAP = config.ROOT / "node_modules" / "gsap" / "dist" / "gsap.min.js"


def run(cmd: list, cwd: Path | None = None, timeout: float | None = None) -> str:
    """Run a kit command; return its output, or raise with the end of its error text."""
    env = {"DO_NOT_TRACK": "1",  # no HyperFrames usage telemetry
           **os.environ, "PATH": f"{NODE_BIN}{os.pathsep}{os.environ.get('PATH', '')}"}
    result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"{Path(str(cmd[1] if cmd[0] == 'node' else cmd[0])).name} failed:\n"
                           f"{(result.stderr or result.stdout)[-2000:]}")
    return result.stdout


# ---------- set up ----------

def new_project(video: Path, client_id: str) -> Path:
    """Same as the kit's `npm run new-video`, but in the drafts folder."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    project = config.DRAFTS_DIR / client_id / f"{video.stem}-{stamp}"
    shutil.copytree(STARTER, project)
    for sub in ("assets", "compositions", "renders"):
        (project / sub).mkdir(exist_ok=True)
    shutil.copy2(GSAP, project / "assets" / "gsap.min.js")
    shutil.copy2(video, project / "assets" / "raw.mp4")
    meta = json.loads((project / "meta.json").read_text())
    meta["name"] = video.stem
    (project / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return project


def kit_transcript(tx: dict) -> dict:
    """Our faster-whisper transcript in the kit's (ElevenLabs Scribe) word format."""
    words = [{"text": w["word"], "start": w["start"], "end": w["end"], "type": "word"}
             for seg in tx["segments"] for w in seg["words"] if w["word"]]
    return {"text": " ".join(w["text"] for w in words), "language_code": "en",
            "audio_duration_secs": round(tx["duration"], 3), "words": words}


def prepare(project: Path, work: Path) -> None:
    """Transcribe, cut silences, and list mistake candidates for Claude to review."""
    assets = project / "assets"
    tx = transcribe(assets / "raw.mp4", work)
    (assets / "raw.json").write_text(json.dumps(kit_transcript(tx), indent=1))
    run(["node", CUT_SILENCES, assets / "raw.json", "--video", assets / "raw.mp4", "--apply",
         "--output", assets / "silenced.mp4"])
    run(["node", FIND_CUTS, assets / "raw.silence-transcript.json", "--out-dir", assets])
    shutil.copy2(assets / "raw.silence-transcript.json", assets / "transcript.json")


# ---------- what Claude reads ----------

def numbered_words(transcript: dict, per_line: int = 14) -> str:
    """Transcript as short timed lines, with every word kept so anchors can be copied exactly."""
    words = transcript["words"]
    lines = [f"Total length: {transcript.get('audio_duration_secs', 0):.1f}s"]
    line: list = []
    for w in words:
        line.append(w)
        if len(line) >= per_line or w["text"].rstrip().endswith((".", "?", "!")):
            lines.append(f"{line[0]['start']:.2f}-{line[-1]['end']:.2f}  " + " ".join(x["text"] for x in line))
            line = []
    if line:
        lines.append(f"{line[0]['start']:.2f}-{line[-1]['end']:.2f}  " + " ".join(x["text"] for x in line))
    return "\n".join(lines)


def current_transcript(project: Path) -> dict:
    return json.loads((project / "assets" / "transcript.json").read_text())


def cut_candidates(project: Path) -> list:
    found = sorted((project / "assets").glob("*.cut-candidates.json"))
    if not found:
        return []
    data = json.loads(found[0].read_text())
    return data.get("candidates", data) if isinstance(data, dict) else data


def frame_png(project: Path, seconds: float) -> bytes:
    """One frame of the silenced video, 960 wide, to see where the face sits."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, seconds):.2f}",
                          "-i", str(project / "assets" / "silenced.mp4"), "-frames:v", "1",
                          "-vf", "scale=960:-2", "-f", "image2pipe", "-c:v", "png", "-"],
                         capture_output=True, check=True)
    return out.stdout


# ---------- mistake cuts ----------

def choose_cuts(project: Path, cuts: list[dict]) -> dict:
    """Re-time the transcript for the chosen cuts without re-encoding (that happens in render).

    Returns the transcript that matches the final video; the plan's anchors are written against it.
    """
    assets = project / "assets"
    silenced_tx = assets / "raw.silence-transcript.json"
    if not cuts:
        (assets / "approved-cuts.json").unlink(missing_ok=True)
        shutil.copy2(silenced_tx, assets / "transcript.json")
        return current_transcript(project)
    for c in cuts:
        if not (isinstance(c.get("start"), (int, float)) and isinstance(c.get("end"), (int, float))
                and 0 <= c["start"] < c["end"]):
            raise ValueError(f"bad cut {c}: needs start < end, in seconds")
    (assets / "approved-cuts.json").write_text(json.dumps({"cuts": cuts}, indent=2))
    run(["node", APPLY_CUTS, silenced_tx, "--cuts", assets / "approved-cuts.json",
         "--video", assets / "silenced.mp4", "--out-dir", assets])
    shutil.copy2(next(assets.glob("*.mistakes-transcript.json")), assets / "transcript.json")
    return current_transcript(project)


# ---------- the plan ----------

def final_video(project: Path) -> str:
    """The plan's video: clean.mp4 once cuts are applied, else silenced.mp4."""
    return "assets/clean.mp4" if (project / "assets" / "approved-cuts.json").exists() else "assets/silenced.mp4"


def check_plan(project: Path, plan: dict) -> str:
    """Save the plan and run the builder's --check. Returns the timing table; raises on errors.

    Before the cuts are rendered, clean.mp4 doesn't exist yet, so the check reads the
    silenced video with the cut transcript's length. render() swaps the real video in.
    """
    plan = dict(plan)
    plan["video"] = final_video(project)
    plan["transcript"] = "assets/transcript.json"
    (project / "lesson-plan.json").write_text(json.dumps(plan, indent=2))
    check = dict(plan)
    if not (project / plan["video"]).exists():
        check["video"] = "assets/silenced.mp4"
        check["duration"] = current_transcript(project)["audio_duration_secs"]
    tmp = project / "lesson-plan.check.json"
    tmp.write_text(json.dumps(check, indent=2))
    try:
        return _build(project, tmp, "--check")
    finally:
        tmp.unlink(missing_ok=True)


def _build(project: Path, plan_file: Path, *flags: str) -> str:
    """build-lesson.mjs always reads lesson-plan.json, so swap a different plan in for the call."""
    real = project / "lesson-plan.json"
    if plan_file == real:
        return run(["node", BUILD, project, *flags])
    saved = real.read_text()
    shutil.copy2(plan_file, real)
    try:
        return run(["node", BUILD, project, *flags])
    finally:
        real.write_text(saved)


def image_beats(plan: dict) -> list[dict]:
    """Beats that want a picture: [{"id", "image", "prompt", "aspect"}]."""
    out = []
    for b in plan.get("beats", []):
        if b.get("imagePrompt") and b.get("image"):
            out.append({"id": b["id"], "image": b["image"], "prompt": b["imagePrompt"],
                        "aspect": "4:3" if b.get("type") == "image" else "3:4"})
    return out


def drop_missing_images(project: Path, plan: dict) -> list[str]:
    """Remove image fields whose file never got made, so the lesson still renders. Returns beat ids."""
    dropped = []
    for b in plan.get("beats", []):
        if b.get("image") and not (project / b["image"]).exists():
            dropped.append(b["id"])
            b.pop("image", None)
            b.pop("imagePrompt", None)
    plan["beats"] = [b for b in plan.get("beats", []) if not (b.get("type") == "image" and not b.get("image"))]
    return dropped


# ---------- render ----------

def render(project: Path, quality: str = "draft") -> Path:
    """Apply the mistake cuts, build, lint, preflight, render. Returns the mp4."""
    assets = project / "assets"
    plan = json.loads((project / "lesson-plan.json").read_text())
    if (assets / "approved-cuts.json").exists() and not (assets / "clean.mp4").exists():
        run(["node", APPLY_CUTS, assets / "raw.silence-transcript.json", "--cuts", assets / "approved-cuts.json",
             "--video", assets / "silenced.mp4", "--output", assets / "clean.mp4", "--out-dir", assets, "--apply"])
    plan["video"] = final_video(project)
    plan.pop("duration", None)
    drop_missing_images(project, plan)
    (project / "lesson-plan.json").write_text(json.dumps(plan, indent=2))

    run(["node", BUILD, project])
    run(["hyperframes", "lint"], cwd=project)
    run(["node", PREFLIGHT, "."], cwd=project)
    out = project / "renders" / f"{project.name.rsplit('-', 2)[0]} - course {quality}.mp4"
    # Railway shows the container every host CPU, so "auto" workers start too many browsers and
    # frame capture times out. Cap them, and give each capture call more time.
    run(["hyperframes", "render", "--quality", quality, "--output", out, "--quiet",
         "--workers", os.environ.get("RENDER_WORKERS", "4"),
         "--protocol-timeout", os.environ.get("RENDER_PROTOCOL_TIMEOUT_MS", "900000")], cwd=project)
    return out
