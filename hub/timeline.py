"""The edit's timeline: which stretches of the raw video are kept, and where things land in the Reel.

Claude picks the stretches to keep (in raw-video seconds, from the transcript). The recipe
can also ask for every pause between words to be cut, which turns a slow teleprompter read
into Maria's no-dead-air pace. Everything else (captions, hook, zooms) is placed on the
finished Reel's clock, so this module maps raw times to Reel times.
"""

AIR_BEFORE = 0.08   # keep a breath before a word after a pause cut
AIR_AFTER = 0.12    # and a little after, so the word's tail isn't clipped


def all_words(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s.get("words", []) if w["word"].strip()]


def snap(transcript: dict, segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Move each segment's edges out to word edges, so a cut never lands mid-word."""
    words = all_words(transcript)
    if not words:
        return segments
    out = []
    for start, end in segments:
        before = [w["start"] for w in words if w["start"] <= start + 0.25]
        after = [w["end"] for w in words if w["end"] >= end - 0.25]
        s = max(before) if before else words[0]["start"]
        e = min(after) if after else words[-1]["end"]
        out.append((max(0.0, s - 0.1), min(transcript["duration"], e + 0.3)))
    return merge(out)


def merge(segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sort and join overlapping segments."""
    out: list[tuple[float, float]] = []
    for s, e in sorted(segments):
        if e <= s:
            continue
        if out and s <= out[-1][1] + 0.01:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def cut_pauses(transcript: dict, segments: list[tuple[float, float]], max_gap: float | None) -> list[tuple[float, float]]:
    """Split segments wherever the speaker is silent for longer than max_gap seconds."""
    if not max_gap:
        return segments
    words = all_words(transcript)
    out = []
    for s, e in segments:
        inside = [w for w in words if w["start"] >= s - 0.05 and w["end"] <= e + 0.05]
        if not inside:
            out.append((s, e))
            continue
        cur_start = s
        for a, b in zip(inside, inside[1:]):
            if b["start"] - a["end"] > max_gap:
                out.append((cur_start, a["end"] + AIR_AFTER))
                cur_start = b["start"] - AIR_BEFORE
        out.append((cur_start, e))
    return merge(out)


def length(segments: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in segments)


def to_reel(segments: list[tuple[float, float]], t: float) -> float | None:
    """Raw-video time -> Reel time, or None when t was cut out."""
    offset = 0.0
    for s, e in segments:
        if s - 1e-6 <= t <= e + 1e-6:
            return offset + (t - s)
        offset += e - s
    return None


def reel_words(transcript: dict, segments: list[tuple[float, float]]) -> list[dict]:
    """Every kept word with its time on the Reel's clock."""
    out = []
    for w in all_words(transcript):
        start, end = to_reel(segments, w["start"]), to_reel(segments, w["end"])
        if start is None or end is None:
            continue
        text = w["word"].strip()
        # Whisper splits "8,463" into "8" + ",463"; join them back
        if out and text[0] in ",.%" and len(text) > 1:
            out[-1]["text"] += text
            out[-1]["end"] = end
            continue
        out.append({"start": start, "end": end, "text": text})
    return out
