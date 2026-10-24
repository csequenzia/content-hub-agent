import json

from hub import drafts, looks, media, recipes, timeline


def test_unknown_template_gets_house_style():
    r = recipes.load_recipe("nope")
    assert r["captions"]["look"] == "caps3" and "template" not in r
    assert recipes.load_recipe("../etc/passwd")["name"] == "House style"


def test_every_recipe_loads_and_uses_known_looks():
    for rid in recipes.available():
        r = recipes.load_recipe(rid)
        assert r["template"] == rid and r["name"]
        assert r["captions"]["look"] in ("caps3", "word", "plain", "pill", "stack")
        assert r["hook"]["look"] in ("pill", "boxes", "none")
        assert r["length"]["min"] < r["length"]["max"]
        assert all(1.0 <= s["zoom"] <= 2.0 and 0 <= s["at"] <= 1 for s in r["shots"])


def test_pause_cuts_and_reel_clock():
    # three 10-word sentences, 0.1s between words, 1.4s of silence between sentences
    words, t = [], 0.0
    for n in range(3):
        for i in range(10):
            words.append({"start": round(t, 2), "end": round(t + 0.3, 2), "word": f"w{n}_{i}"})
            t += 0.4
        t += 1.4
    transcript = {"duration": t, "segments": [{"start": 0, "end": t, "text": "", "words": words}]}
    segs = timeline.cut_pauses(transcript, [(0.0, 15.0)], max_gap=0.3)
    assert len(segs) == 3
    assert timeline.length(segs) < 15.0
    words = timeline.reel_words(transcript, segs)
    assert len(words) == 30
    assert all(b["start"] >= a["start"] for a, b in zip(words, words[1:]))
    assert timeline.to_reel(segs, 4.6) is None          # inside a cut pause


def test_stack_captions_build_up_word_by_word():
    words = [{"start": i * 0.4, "end": i * 0.4 + 0.3, "text": t}
             for i, t in enumerate("Here's an Instagram story that you can post today.".split())]
    events = looks.stack_events(words, {"can"}, {})
    assert len(events) == len(words)
    assert "\\N{\\fs100}CAN\\N" in events[-1][2]         # the emphasis word is big, on its own line
    assert events[-1][2].count("\\N") >= 3                # lines pile up
    assert events[0][2].endswith("HERE'S")


def test_r09_render(sample_video, transcript, tmp_dirs):
    recipe = recipes.load_recipe("R09")
    plan = {"segments": [{"start": 5.0, "end": 30.0}], "hook": "I've coached 7,000 Christians:",
            "hook_lines": ["I've coached 7,000 Christians:", "this is partially how:"],
            "post_caption": "x", "why": "test"}
    out = drafts.render_draft(sample_video, "healthy-free-life", transcript, plan, recipe=recipe)
    info = media.probe(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 24 <= info["duration"] <= 26
    assert (out.parent / "hook.png").exists()
    assert json.loads((out.parent / "post.json").read_text())["recipe"] == "R09"


def test_recipe_length_rules(transcript):
    recipe = recipes.load_recipe("R09")
    plan = {"start": 0, "end": 50, "hook": "h", "post_caption": "c"}
    assert "must be 18-35s" in drafts.validate_plan(plan, transcript, recipe)[0]
    assert drafts.validate_plan({**plan, "end": 25}, transcript, recipe) == []
