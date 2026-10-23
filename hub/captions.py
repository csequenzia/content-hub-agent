"""Burned-in captions and hook text, written as an ASS subtitle file for ffmpeg.

The look follows Greg's Talking Head Videos pipeline: 3-word ALL-CAPS chunks,
bold font, white fill, black outline, sitting at y ≈ 1480. Colors come from the
client's brand kit when it has them.
"""

import re
from pathlib import Path

from . import config


def ass_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        cs, s = 0, int(s) + 1
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def ass_color(hex_color: str) -> str:
    """'#6a50a3' -> '&H00A3506A' (ASS colors are &HAABBGGRR)."""
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def fix_words(text: str) -> str:
    for wrong, right in config.CAPTION_REPLACEMENTS.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
    return text


def words_in_range(transcript: dict, start: float, end: float) -> list[dict]:
    """Words fully inside [start, end], with times shifted so the clip starts at 0."""
    words = []
    for seg in transcript["segments"]:
        for w in seg.get("words", []):
            text = w["word"].strip()
            if not text or w["start"] < start - 0.05 or w["end"] > end + 0.05:
                continue
            # Whisper splits "8,463" into "8" + ",463"; join them back
            if words and text[0] in ",.%" and len(text) > 1:
                words[-1]["text"] += text
                words[-1]["end"] = w["end"] - start
                continue
            words.append({"start": w["start"] - start, "end": w["end"] - start, "text": text})
    return words


def chunk_words(words: list[dict], per_chunk: int = config.CAPTION_WORDS_PER_CHUNK) -> list[tuple]:
    chunks = []
    for i in range(0, len(words), per_chunk):
        group = words[i:i + per_chunk]
        nxt = i + per_chunk
        end = words[nxt]["start"] if nxt < len(words) else group[-1]["end"] + config.CAPTION_TAIL_SECONDS
        text = fix_words(" ".join(w["text"] for w in group)).upper()
        chunks.append((group[0]["start"], end, text))
    return chunks


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def write_ass(chunks: list[tuple], hook_text: str, brand: dict, out: Path) -> Path:
    colors = brand.get("colors", {})
    cap = colors.get("caption", {"fill": "#FFFFFF", "outline": "#000000"})
    hook = colors.get("hook", {"bg": "#000000", "fg": "#FFFFFF"})
    font = config.CAPTION_FONT
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.OUTPUT_WIDTH}
PlayResY: {config.OUTPUT_HEIGHT}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{config.CAPTION_FONT_SIZE},{ass_color(cap['fill'])},{ass_color(cap['fill'])},{ass_color(cap['outline'])},&H00000000,1,0,0,0,100,100,0,0,1,{config.CAPTION_OUTLINE},2,2,{config.CAPTION_MARGIN_LR},{config.CAPTION_MARGIN_LR},{config.CAPTION_MARGIN_BOTTOM},1
Style: Hook,{font},{config.HOOK_FONT_SIZE},{ass_color(hook['fg'])},{ass_color(hook['fg'])},{ass_color(hook['bg'])},{ass_color(hook['bg'])},1,0,0,0,100,100,0,0,3,18,0,8,{config.HOOK_MARGIN_SIDES},{config.HOOK_MARGIN_SIDES},{config.HOOK_MARGIN_TOP},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    if hook_text:
        lines.append(f"Dialogue: 1,{ass_ts(0)},{ass_ts(config.HOOK_SECONDS)},Hook,,0,0,0,,"
                     f"{_escape(hook_text.upper())}")
    for start, end, text in chunks:
        lines.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(end)},Caption,,0,0,0,,{_escape(text)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
