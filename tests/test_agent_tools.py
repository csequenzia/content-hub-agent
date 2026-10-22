"""Exercises the agent's tools the way Claude would call them, without an API key."""

import asyncio
import json

from hub import agent

from .conftest import fake_transcript


def _tools(sample_video, tmp_dirs, result):
    work = tmp_dirs / "work" / "sample-clinic" / sample_video.stem
    work.mkdir(parents=True)
    (work / "transcript.json").write_text(json.dumps(fake_transcript()))  # skips Whisper
    return {t.name: t for t in agent.build_tools(sample_video, "sample-clinic", work, result)}


def call(t, args):
    return asyncio.run(t.handler(args))


def test_transcript_and_brand_tools(sample_video, tmp_dirs):
    tools = _tools(sample_video, tmp_dirs, {})
    tx = call(tools["get_transcript"], {})["content"][0]["text"]
    assert tx.startswith("Total length: 70.0s")
    assert "[1] 5.00-9.90" in tx
    brand = json.loads(call(tools["get_brand_kit"], {})["content"][0]["text"])
    assert "never_say" in brand


def test_render_tool_reports_problems_then_succeeds(sample_video, tmp_dirs):
    result = {}
    tools = _tools(sample_video, tmp_dirs, result)
    bad = call(tools["render_draft"], {"start": 0, "end": 12, "hook": "x", "post_caption": "y", "why": "z"})
    assert bad.get("is_error") and "30-60s" in bad["content"][0]["text"]
    good = call(tools["render_draft"], {"start": 10, "end": 50, "hook": "Your knee is not broken",
                                         "post_caption": "It just needs load.", "why": "best hook"})
    assert "Draft saved" in good["content"][0]["text"]
    assert result["draft"].exists()
