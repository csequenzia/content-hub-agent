"""Course lesson mode: Katrina's edit-course-lesson kit driven from Python.

The end-to-end tests need Node 22, the npm packages (npm ci) and ffmpeg 7+, like the
Docker image. They skip where those are missing. Set HUB_TEST_RENDER=1 to also render
with HyperFrames (needs Chrome; set HYPERFRAMES_BROWSER_PATH if it isn't found).
"""

import asyncio
import io
import json
import os
import shutil
import subprocess

import pytest

from hub import agent, config, course, higgsfield


def kit_ready() -> bool:
    if os.environ.get("HUB_TEST_KIT") == "1":   # force on, e.g. with an ffmpeg 6 wrapper that maps -/filter_complex
        return True
    if not (shutil.which("node") and course.GSAP.exists() and shutil.which("ffmpeg")):
        return False
    help_text = subprocess.run(["ffmpeg", "-h"], capture_output=True, text=True).stdout
    return "-/" in help_text or "ffmpeg version 7" in subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True).stdout


needs_kit = pytest.mark.skipif(not kit_ready(), reason="needs node, npm ci and ffmpeg 7+")

SENTENCES = ("Welcome to lesson lesson one on gut health basics. Today we cover fiber and water. "
             "First fiber feeds the good bacteria in your gut. Most people eat far too little fiber. "
             "Second water helps everything move along. So remember fiber and water every single day.")


def lesson_transcript() -> dict:
    """Our faster-whisper shape, with long pauses between sentences and one stutter."""
    words, t = [], 0.5
    for w in SENTENCES.split():
        words.append({"word": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
        t += 0.4 + (1.5 if w.endswith(".") else 0)
    return {"duration": 40.0, "segments": [{"start": 0.5, "end": t, "text": SENTENCES, "words": words}]}


PLAN = {
    "title": "Lesson 1: Gut health basics",
    "imageStyle": "Clean minimal flat illustration, no text",
    "camera": {"events": [{"at": 0, "mode": "full"}, {"atAnchor": "First fiber", "mode": "box"}]},
    "beats": [
        {"id": "title", "type": "title", "start": 0.1, "endAnchor": "fiber and water",
         "kicker": "Lesson 1", "title": "Gut health basics"},
        {"id": "fiber", "type": "takeaway", "startAnchor": "First fiber", "label": "Step one",
         "heading": "Fiber feeds your gut", "points": [{"text": "Feeds the good bacteria", "atAnchor": "good bacteria"}],
         "image": "assets/aids/fiber.png", "imagePrompt": "a bowl of oats and berries"},
        {"id": "water", "type": "section", "startAnchor": "Second water", "number": "2", "heading": "Water"},
    ],
}


def test_kit_transcript_format():
    kit = course.kit_transcript(lesson_transcript())
    assert kit["audio_duration_secs"] == 40.0
    assert kit["words"][0] == {"text": "Welcome", "start": 0.5, "end": 0.8, "type": "word"}
    assert kit["text"].startswith("Welcome to lesson lesson one")


def test_numbered_words_keeps_every_word():
    kit = course.kit_transcript(lesson_transcript())
    text = course.numbered_words(kit)
    assert text.splitlines()[1].endswith("Welcome to lesson lesson one on gut health basics.")
    assert sum(len(line.split()) - 1 for line in text.splitlines()[1:]) == len(kit["words"])


def test_missing_images_are_dropped(tmp_path):
    plan = json.loads(json.dumps(PLAN))
    plan["beats"].append({"id": "pic", "type": "image", "start": 9, "heading": "x",
                          "image": "assets/aids/pic.png", "imagePrompt": "y"})
    assert course.drop_missing_images(tmp_path, plan) == ["fiber", "pic"]
    assert "image" not in plan["beats"][1] and [b["id"] for b in plan["beats"]] == ["title", "fiber", "water"]


@pytest.fixture
def lesson(sample_video, tmp_dirs, monkeypatch):
    work = tmp_dirs / "work"
    work.mkdir()
    (work / "transcript.json").write_text(json.dumps(lesson_transcript()))  # skips Whisper
    project = course.new_project(sample_video, "sample-clinic")
    course.prepare(project, work)
    return project


@needs_kit
def test_course_tools_end_to_end(lesson, monkeypatch):
    result: dict = {}
    tools = {t.name: t for t in agent.build_course_tools(lesson, result)}
    call = lambda name, args: asyncio.run(tools[name].handler(args))

    first = call("get_lesson_transcript", {})["content"][0]["text"]
    assert "lesson lesson" in first and '"type": "stutter"' in first
    assert call("check_lesson_plan", {"plan": PLAN}).get("is_error")       # cuts come first
    stutter = course.cut_candidates(lesson)[0]["cut"]
    cut = call("choose_mistake_cuts", {"cuts": [{**stutter, "reason": "stutter"}]})["content"][0]["text"]
    assert "lesson one" in cut and "lesson lesson" not in cut
    assert call("choose_mistake_cuts", {"cuts": []}).get("is_error")      # only once

    bad = call("check_lesson_plan", {"plan": {**PLAN, "beats": [{**PLAN["beats"][0], "endAnchor": "not said"}]}})
    assert bad.get("is_error")
    assert call("finish_lesson", {"note": "x"}).get("is_error")             # plan not checked yet
    table = call("check_lesson_plan", {"plan": PLAN})["content"][0]["text"]
    assert "| fiber | takeaway |" in table
    saved = json.loads((lesson / "lesson-plan.json").read_text())
    assert saved["video"] == "assets/clean.mp4" and saved["transcript"] == "assets/transcript.json"

    frame = call("look_at_frame", {"seconds": 2})["content"][0]
    assert frame["type"] == "image" and len(frame["data"]) > 1000

    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    assert "Images are off" in call("generate_image", {"beat_id": "fiber"})["content"][0]["text"]

    made = []
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "id:secret")
    monkeypatch.setattr(higgsfield, "generate_image",
                        lambda prompt, out, aspect, *a: (made.append((prompt, aspect)), out.parent.mkdir(exist_ok=True),
                                                         shutil.copy(course.STARTER / "meta.json", out)))
    assert "Saved" in call("generate_image", {"beat_id": "fiber"})["content"][0]["text"]
    assert made == [("a bowl of oats and berries. Style: Clean minimal flat illustration, no text", "3:4")]
    assert call("generate_image", {"beat_id": "title"}).get("is_error")
    assert "Rendering" in call("finish_lesson", {"note": "Cut one stutter."})["content"][0]["text"]

    if os.environ.get("HUB_TEST_RENDER") == "1":
        (lesson / "assets/aids/fiber.png").unlink()   # not a real image; the render drops it
        out = course.render(lesson)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(out)], capture_output=True, text=True, check=True).stdout
        assert out.exists() and abs(float(probe) - course.current_transcript(lesson)["audio_duration_secs"]) < 1


def test_higgsfield_request_and_download(tmp_path, monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "id:secret")
    calls = []

    def fake_request(method, url, body=None, idempotency=None):
        calls.append((method, url, body))
        if method == "POST":
            return {"status": "queued", "request_id": "r1", "status_url": "https://api.higgsfield.ai/requests/r1/status"}
        return {"status": "completed", "images": [{"url": "https://cdn.example/x.png"}]}

    monkeypatch.setattr(higgsfield, "_request", fake_request)
    monkeypatch.setattr(higgsfield.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"PNGDATA"))
    out = higgsfield.generate_image("a glass of water", tmp_path / "a.png", "4:3", [(1, 2, 3)], (255, 255, 255), poll=0)
    assert out.read_bytes() == b"PNGDATA"
    method, url, body = calls[0]
    assert url == "https://api.higgsfield.ai/recraft/v4.1/text-to-image"
    assert body == {"prompt": "a glass of water", "aspect_ratio": "4:3", "output_format": "png", "resolution": "1k",
                    "colors": [{"rgb": [1, 2, 3]}], "background_color": {"rgb": [255, 255, 255]}}


def test_higgsfield_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "id:secret")
    monkeypatch.setattr(higgsfield, "_request", lambda *a, **k: {"status": "nsfw", "request_id": "r"})
    with pytest.raises(RuntimeError, match="nsfw"):
        higgsfield.generate_image("x", tmp_path / "a.png", poll=0)


def test_reels_agent_does_not_see_course_skills():
    names = agent.reels_skills()
    assert "reels-edit-style" in names and "edit-course-lesson" not in names and "cut-silences" not in names
