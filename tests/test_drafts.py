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
