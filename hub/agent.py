"""The editing agent, built on Anthropic's Claude Agent SDK.

Claude gets three tools that run inside this Python process:
  get_transcript  - the raw video's transcript, one numbered sentence per line with times
  get_brand_kit   - the client's voice, audience, offers, never-say list and colors
  render_draft    - cuts the chosen clip, burns captions + hook, adds the logo, saves the draft

It also gets the skills in .claude/skills/ (Greg's editing and script skills go there),
so the editing rules live in plain files Greg can change without touching code.
"""

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

from . import config
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
        skills="all",                    # everything in .claude/skills/
        cwd=str(config.ROOT),
        max_turns=config.MAX_AGENT_TURNS,
        max_budget_usd=config.MAX_BUDGET_USD,
    )
    prompt = f"New raw video from client '{client_id}': {video.name}. Make the first draft."

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
    if "draft" not in result:
        raise RuntimeError(f"agent finished without rendering a draft: {' '.join(summary)[-500:]}")
    result["summary"] = summary[-1] if summary else ""
    return result
