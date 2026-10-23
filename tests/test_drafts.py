import json

import pytest

from hub import drafts, media

PLAN = {"start": 5.0, "end": 45.0, "hook": "Stop icing your knee",
        "post_caption": "Ice is not a plan.\nComment KNEE for the guide.", "hashtags": ["#kneepain"],
        "why": "Strongest opening line"}


def test_plan_length_rules(transcript):
    assert drafts.validate_plan(PLAN, transcript) == []
    assert "must be 30-60s" in drafts.validate_plan({**PLAN, "end": 20.0}, transcript)[0]
    assert "must be 30-60s" in drafts.validate_plan({**PLAN, "end": 69.0}, transcript)[0]
    assert "inside the video" in drafts.validate_plan({**PLAN, "end": 90.0}, transcript)[0]
    assert drafts.validate_plan({"start": 1}, transcript)  # missing fields


def test_snap_never_cuts_mid_word(transcript):
    start, end = drafts.snap_to_words(transcript, 5.2, 44.95)
    assert start == pytest.approx(4.9)   # first word at 5.0, minus a little air
    assert end == pytest.approx(45.2)    # word ending at 44.9 is kept whole, plus air


def test_render_draft_end_to_end(sample_video, transcript, tmp_dirs):
    out = drafts.render_draft(sample_video, "sample-clinic", transcript, PLAN)
    assert out.exists()
    info = media.probe(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 39 <= info["duration"] <= 41.5
    post = json.loads((out.parent / "post.json").read_text())
    assert post["status"] == "needs_review"
    assert post["hook"] == PLAN["hook"]


def test_bad_plan_is_rejected_before_rendering(sample_video, transcript, tmp_dirs):
    with pytest.raises(ValueError):
        drafts.render_draft(sample_video, "sample-clinic", transcript, {**PLAN, "end": 10.0})
    assert not (tmp_dirs / "drafts").exists()


def test_join_clips(tmp_path):
    import shutil
    import subprocess

    import pytest

    from hub import media
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    a, b = tmp_path / "a.mp4", tmp_path / "b.webm"
    # a portrait take with sound, then a landscape take with no sound (camera flipped, say)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(a)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=1.5",
                    "-c:v", "libvpx", "-deadline", "realtime", str(b)], check=True)
    out = media.join_clips([a, b], tmp_path / "joined.mp4")
    info = media.probe(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 3.3 < info["duration"] < 3.8 and media.has_stream(out, "a")

    single = media.join_clips([b], tmp_path / "one.mp4")    # a lone WebM take still becomes an MP4 with sound
    assert media.probe(single)["height"] == 1920 and media.has_stream(single, "a")
    silent = tmp_path / "sound-only.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=1", str(silent)], check=True)
    with pytest.raises(RuntimeError, match="no picture"):
        media.join_clips([a, silent], tmp_path / "bad.mp4")


def test_render_survives_punctuation_in_the_video_name(sample_video, transcript, tmp_path):
    # Content Studio names the upload after the hook, e.g. "I've coached 7,000 Christians"
    odd = tmp_path / "I've coached 7,000 Christians: [part 1].mp4"
    odd.write_bytes(sample_video.read_bytes())
    out = drafts.render_draft(odd, "sample-clinic", transcript, PLAN, drafts_dir=tmp_path / "drafts")
    assert out.exists()
    assert out.name == "I've coached 7,000 Christians: [part 1] - first draft.mp4"
