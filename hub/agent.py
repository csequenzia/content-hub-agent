"""The editing agent, built on Anthropic's Claude Agent SDK.

Claude gets three tools that run inside this Python process:
  get_transcript  - the raw video's transcript, one numbered sentence per line with times
  get_brand_kit   - the client's voice, audience, offers, never-say list and colors
  render_draft    - cuts the chosen clip, burns captions + hook, adds the logo, saves the draft

It also gets the skills in .claude/skills/ (Greg's editing and script skills go there),
so the editing rules live in plain files Greg can change without touching code.

Course lessons (edit_course) use Katrina's edit-course-lesson skill with a different
tool set; see COURSE_PROMPT and build_course_tools below.
"""

import asyncio
import base64
import json
import os
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from . import config, course, higgsfield
from .brand import load_brand
from .drafts import render_draft
from .transcribe import as_numbered_text, transcribe

SYSTEM_PROMPT = f"""You are the first-draft video editor for a content agency that makes
Instagram Reels for allied health professionals (PTs, OTs, SLPs, chiropractors,
dietitians). A client uploaded a raw video. Your job is to turn it into one strong
{config.MIN_CLIP_SECONDS}-{config.MAX_CLIP_SECONDS} second Reel that a human editor
will review before it is posted.

Work in this order:
1. Call get_brand_kit and get_transcript.
2. If a skill in your skill list covers this kind of video or the client's voice, use it.
3. Choose ONE continuous section of the transcript that works on its own: it opens with a
   line that stops the scroll, makes one clear point, and ends on a complete thought.
   Prefer the section with the strongest opening line over the one with the most information.
   Start and end on sentence boundaries from the transcript.
4. Write the on-screen hook (under 8 words, in the client's voice, never clickbait the
   clip can't back up) and the Instagram post caption (2-5 short lines in the client's
   voice, ending with the client's call to action if they have one).
5. Call render_draft once. If it returns a problem, fix the plan and call it again.

Never use anything on the client's never-say list. Never make medical claims the
speaker did not make. When you finish, reply with two sentences: what you picked and why.
"""


def build_tools(video: Path, client_id: str, work: Path, result: dict):
    transcript_cache: dict = {}

    def get_tx() -> dict:
        if not transcript_cache:
            transcript_cache.update(transcribe(video, work))
        return transcript_cache

    @tool("get_transcript", "Transcript of the raw video, one numbered sentence per line with start-end seconds.", {})
    async def get_transcript(args):
        return {"content": [{"type": "text", "text": as_numbered_text(get_tx())}]}

    @tool("get_brand_kit", "The client's brand kit: voice, audience, offers, story, never-say list, CTA, colors.", {})
    async def get_brand_kit(args):
        brand = load_brand(client_id)
        return {"content": [{"type": "text", "text": json.dumps(brand, indent=2)}]}

    @tool(
        "render_draft",
        "Render the first draft. start/end are seconds in the raw video (use sentence times from the "
        f"transcript); the clip must be {config.MIN_CLIP_SECONDS}-{config.MAX_CLIP_SECONDS}s long.",
        {
            "type": "object",
            "properties": {
                "start": {"type": "number", "description": "Clip start, seconds in the raw video"},
                "end": {"type": "number", "description": "Clip end, seconds in the raw video"},
                "hook": {"type": "string", "description": "On-screen hook for the first seconds, under 8 words"},
                "post_caption": {"type": "string", "description": "Instagram caption in the client's voice"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
                "why": {"type": "string", "description": "One sentence for the reviewer: why this section"},
            },
            "required": ["start", "end", "hook", "post_caption", "why"],
        },
    )
    async def render_draft_tool(args):
        try:
            out = render_draft(video, client_id, get_tx(), args)
        except ValueError as problem:
            return {"content": [{"type": "text", "text": f"Not rendered: {problem}. Adjust and try again."}],
                    "is_error": True}
        result["draft"] = out
        result["plan"] = args
        return {"content": [{"type": "text", "text": f"Draft saved: {out}"}]}

    return [get_transcript, get_brand_kit, render_draft_tool]


async def edit_video(video: Path, client_id: str, log=print) -> dict:
    """Run the agent on one raw video. Returns {"draft": Path, "plan": dict, "summary": str, "cost_usd": float}.

    `log` receives each thing Claude says along the way (the upload page shows these).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set (see .env.example)")
    video = video.resolve()
    work = config.WORK_DIR / client_id / video.stem
    result: dict = {}
    server = create_sdk_mcp_server(name="hub", tools=build_tools(video, client_id, work, result))
    tool_names = ["mcp__hub__get_transcript", "mcp__hub__get_brand_kit", "mcp__hub__render_draft"]

    options = ClaudeAgentOptions(
        model=config.CLAUDE_MODEL,
        effort=config.CLAUDE_EFFORT,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"hub": server},
        strict_mcp_config=True,          # only our tools, never MCP servers from the machine's settings
        tools=["Read"],                  # Read lets skills open their reference files
        allowed_tools=[*tool_names, "Read"],
        permission_mode="dontAsk",       # anything not listed above is refused, never prompted
        skills=reels_skills(),           # everything in .claude/skills/ except the course-lesson ones
        cwd=str(config.ROOT),
        max_turns=config.MAX_AGENT_TURNS,
        max_budget_usd=config.MAX_BUDGET_USD,
        max_buffer_size=MAX_BUFFER_SIZE,
    )
    prompt = f"New raw video from client '{client_id}': {video.name}. Make the first draft."

    summary = await _run(prompt, options, result, log)
    if "draft" not in result:
        raise RuntimeError(f"agent finished without rendering a draft: {' '.join(summary)[-500:]}")
    result["summary"] = summary[-1] if summary else ""
    return result


async def _run(prompt: str, options: ClaudeAgentOptions, result: dict, log) -> list[str]:
    """Run one agent conversation; returns what Claude said. Raises if the run ended in an error."""
    summary = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    log(f"  claude: {block.text}")
                    summary.append(block.text)
        elif isinstance(message, ResultMessage):
            result["cost_usd"] = message.total_cost_usd
            if message.is_error:
                result["error"] = f"{message.subtype}: {message.result or message.errors or ''}"

    # Raise only after the loop so the SDK can shut its subprocess down cleanly
    if "error" in result:
        raise RuntimeError(f"agent stopped: {result['error']}")
    return summary


MAX_BUFFER_SIZE = 50 * 1024 * 1024  # SDK default is 1 MB; images the agent reads come back inline

COURSE_SKILLS = ["edit-course-lesson", "cut-mistakes"]
NOT_FOR_REELS = {*COURSE_SKILLS, "cut-silences"}


def reels_skills() -> list[str]:
    skills = config.ROOT / ".claude" / "skills"
    return sorted(p.parent.name for p in skills.glob("*/SKILL.md") if p.parent.name not in NOT_FOR_REELS)


# ---------- course lessons ----------

COURSE_PROMPT = """You are editing a raw course lesson recording into a clean teaching video,
following the edit-course-lesson skill. Read that skill and its references/lesson-plan.md first.

This runs on a server with no person watching, so a few things differ from the skill:
- Steps 1-3 are already done: the video is copied, transcribed, and silence-cut. You never
  run commands. You use these tools instead:
  get_lesson_transcript, look_at_frame, choose_mistake_cuts, check_lesson_plan,
  generate_image, finish_lesson.
- Mistake cuts (step 4): no one approves them live. Cut only clear mistakes: stutters,
  false starts, a botched line that is immediately re-said, tech trouble, asides to a live
  audience. When unsure, keep it. Call choose_mistake_cuts exactly once (an empty list is
  fine); it returns the transcript of the final video. Write every anchor against that one.
- The lesson plan (step 5): call check_lesson_plan with the whole plan and fix every error
  it reports. You do not need anyone to approve it. Leave out "video" and "transcript";
  the tool fills them in. Use look_at_frame on a moment where the speaker is settled to set
  camera.focusX / focusY so the face stays inside the rounded box.
- Images (step 6): call generate_image once per beat that has "image" + "imagePrompt"
  (image paths go under assets/aids/, e.g. "assets/aids/<beat id>.png"). Then open each
  file with Read and look at it. Regenerate once if it has text, letters, extra limbs or
  clutter; if it is still wrong, drop the image from that beat and check the plan again.
  If generate_image says images are off, plan the lesson without images.
- Rendering (steps 7-9) happens after you finish. Do not wait for it.
- Only set "product" if the recording clearly says it is a Glorious Way, Temple Restored
  or Food Revival lesson.

When the plan checks clean and the images are in place, call finish_lesson with a short
note for the reviewer: what you cut, the beats, and anything they should look at.
"""

BRAND_PALETTE = [(42, 64, 32), (132, 160, 95), (220, 229, 200), (209, 60, 91)]  # olive deep, sage, pale sage, pomegranate
WHITE = (255, 255, 255)


def build_course_tools(project: Path, result: dict):
    state = {"images_made": 0}

    def text(t: str, error: bool = False) -> dict:
        out = {"content": [{"type": "text", "text": t}]}
        if error:
            out["is_error"] = True
        return out

    @tool("get_lesson_transcript",
          "The lesson's transcript (after silence cuts, and after your mistake cuts once chosen) as timed "
          "lines with every word, plus the mistake candidates the cut-mistakes detector found.", {})
    async def get_lesson_transcript(args):
        body = course.numbered_words(course.current_transcript(project))
        if "cuts" not in result:
            body += "\n\nMistake candidates (times are on this transcript):\n" + json.dumps(
                course.cut_candidates(project), indent=1)
        return text(body)

    @tool("look_at_frame", "One frame of the lesson video at a time in seconds, to see where the face is.",
          {"seconds": float})
    async def look_at_frame(args):
        png = await asyncio.to_thread(course.frame_png, project, float(args["seconds"]))
        return {"content": [{"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"}]}

    @tool("choose_mistake_cuts",
          "Set the mistake cuts (seconds on the current transcript). Returns the transcript of the final video.",
          {"type": "object",
           "properties": {"cuts": {"type": "array", "items": {"type": "object", "properties": {
               "start": {"type": "number"}, "end": {"type": "number"}, "reason": {"type": "string"}},
               "required": ["start", "end", "reason"]}}},
           "required": ["cuts"]})
    async def choose_mistake_cuts(args):
        if "cuts" in result:
            return text("Cuts are already chosen; write the plan against the transcript you were given.", True)
        try:
            tx = await asyncio.to_thread(course.choose_cuts, project, args["cuts"])
        except (ValueError, RuntimeError) as problem:
            return text(f"Cuts not applied: {problem}", True)
        result["cuts"] = args["cuts"]
        return text(f"{len(args['cuts'])} cut(s) set. Final transcript:\n" + course.numbered_words(tx))

    @tool("check_lesson_plan",
          "Save lesson-plan.json and run the builder's check. Returns the timing table, or the errors to fix.",
          {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"]})
    async def check_lesson_plan(args):
        if "cuts" not in result:
            return text("Call choose_mistake_cuts first (an empty list is fine).", True)
        try:
            table = await asyncio.to_thread(course.check_plan, project, args["plan"])
        except RuntimeError as problem:
            result["plan_ok"] = False
            return text(f"Plan has problems:\n{problem}", True)
        result["plan_ok"] = True
        return text(table)

    @tool("generate_image",
          "Make the image for one beat of the saved plan with Higgsfield (prompt = imagePrompt + imageStyle). "
          "Saves it to the beat's image path.", {"beat_id": str})
    async def generate_image(args):
        if not higgsfield.api_key():
            return text("Images are off on this server (no HIGGSFIELD_API_KEY). Remove image fields and "
                        "check the plan again.", True)
        if state["images_made"] >= config.MAX_COURSE_IMAGES:
            return text(f"Image limit reached ({config.MAX_COURSE_IMAGES} per lesson). Drop the remaining "
                        "images from the plan.", True)
        plan = json.loads((project / "lesson-plan.json").read_text())
        beat = next((b for b in course.image_beats(plan) if b["id"] == args["beat_id"]), None)
        if not beat:
            return text(f"No beat '{args['beat_id']}' with image + imagePrompt in the checked plan.", True)
        out = (project / beat["image"]).resolve()
        if not out.is_relative_to((project / "assets").resolve()):
            return text("Image paths must be inside assets/.", True)
        prompt = beat["prompt"] + (f". Style: {plan['imageStyle']}" if plan.get("imageStyle") else "")
        state["images_made"] += 1
        try:
            await asyncio.to_thread(higgsfield.generate_image, prompt, out.with_suffix(".png"), beat["aspect"],
                                    BRAND_PALETTE, WHITE)
        except Exception as problem:  # network, credits, refused prompt: Claude can drop the image
            return text(f"Higgsfield failed: {problem}", True)
        if out.suffix.lower() != ".png":
            out.with_suffix(".png").replace(out)
        result.setdefault("images", []).append(beat["id"])
        return text(f"Saved {out}. Open it with Read to check it.")

    @tool("finish_lesson", "Done planning. The lesson renders after this.", {"note": str})
    async def finish_lesson(args):
        if not result.get("plan_ok"):
            return text("check_lesson_plan has not passed yet.", True)
        result["note"] = args["note"]
        return text("Thanks. Rendering now.")

    return [get_lesson_transcript, look_at_frame, choose_mistake_cuts, check_lesson_plan,
            generate_image, finish_lesson]


async def edit_course(video: Path, client_id: str, log=print) -> dict:
    """Edit one course lesson. Returns {"draft": Path, "note": str, "cuts": list, "images": list, "cost_usd": float}."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set (see .env.example)")
    video = video.resolve()
    work = config.WORK_DIR / client_id / video.stem
    project = course.new_project(video, client_id)
    log("Transcribing and cutting silences")
    await asyncio.to_thread(course.prepare, project, work)

    result: dict = {"project": project}
    tools = build_course_tools(project, result)
    server = create_sdk_mcp_server(name="course", tools=tools)
    tool_names = [f"mcp__course__{t.name}" for t in tools]
    options = ClaudeAgentOptions(
        model=config.CLAUDE_MODEL,
        effort=config.CLAUDE_EFFORT,
        system_prompt=COURSE_PROMPT,
        mcp_servers={"course": server},
        strict_mcp_config=True,
        tools=["Read"],                  # skill references, and looking at the generated images
        allowed_tools=[*tool_names, "Read"],
        permission_mode="dontAsk",
        skills=COURSE_SKILLS,
        cwd=str(config.ROOT),
        max_turns=config.COURSE_MAX_TURNS,
        max_budget_usd=config.COURSE_MAX_BUDGET_USD,
        max_buffer_size=MAX_BUFFER_SIZE,  # Read on a generated image returns it inline, often over 1 MB
    )
    prompt = f"New course lesson from client '{client_id}': {video.name}. Plan the edit."
    summary = await _run(prompt, options, result, log)
    if "note" not in result:
        raise RuntimeError(f"agent finished without a lesson plan: {' '.join(summary)[-500:]}")

    log("Rendering the lesson (this is the slow part)")
    result["draft"] = await asyncio.to_thread(course.render, project)
    (project / "course.json").write_text(json.dumps(
        {k: result.get(k) for k in ("note", "cuts", "images", "cost_usd")}, indent=2))
    return result
