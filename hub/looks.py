"""The on-screen looks a recipe can ask for: caption styles and hook styles.

Captions (recipe["captions"]["look"]):
  caps3   Greg's house style: 3 words at a time, ALL CAPS, white with a black outline, low on screen
  plain   Instagram-style: normal case, white, soft shadow, 2-3 lines of a sentence, centered
  pill    small sentence-case text on a dark rounded strip, under a pinned hook (Maria's "rules" reels)
  word    one word at a time, ALL CAPS, heavy with an outline, a little below the middle
  stack   Maria's kinetic stack: ALL CAPS, left-aligned, words pile up line by line as they're
          said, line sizes vary and one word per block is big

Hooks (recipe["hook"]["look"]):
  pill    ALL CAPS text on a brand-colored strip at the top (house style), drawn by libass
  boxes   black text on white rounded boxes, one box per line Claude gives (Maria's look),
          drawn as a PNG and laid over the video
  none    no hook on screen

Captions go into one ASS file for ffmpeg's ass filter. Box hooks are PNGs overlaid by media.py.
"""

import re
from pathlib import Path

from . import config
from .captions import _escape, ass_color, ass_ts, fix_words

W, H = config.OUTPUT_WIDTH, config.OUTPUT_HEIGHT
BRAND_FONT_FILE = "DMSans-Bold.ttf"   # in fonts/; the HFL brand font, and close to Instagram's own


def font_name() -> str:
    return "DM Sans" if (config.FONTS_DIR / BRAND_FONT_FILE).exists() else config.CAPTION_FONT


def font_file() -> Path | None:
    for path in (config.FONTS_DIR / BRAND_FONT_FILE, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if path.exists():
            return path
    return None


def _cased(text: str, case: str) -> str:
    return text.upper() if case == "upper" else text


SENTENCE_END = re.compile(r"[.!?]$")


# ---------- caption looks ----------

def chunks_by_words(words: list[dict], max_words: int, case: str) -> list[tuple]:
    """Groups of up to max_words, ending early at a sentence end. Each stays up until the next starts."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or SENTENCE_END.search(w["text"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        end = groups[i + 1][0]["start"] if i + 1 < len(groups) else g[-1]["end"] + config.CAPTION_TAIL_SECONDS
        out.append((g[0]["start"], end, _cased(fix_words(" ".join(w["text"] for w in g)), case)))
    return out


STOP = {"the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for", "is", "it", "i", "my",
        "you", "your", "we", "that", "this", "with", "so", "be", "was", "are", "as", "if", "me", "do"}


def stack_events(words: list[dict], emphasis: set[str], c: dict) -> list[tuple]:
    """Maria's word stack: lines of 1-2 words build up as they're said, one word per block is big
    on a line of its own, and the block clears at the end of a sentence (or after max_words)."""
    max_words, line_chars = c.get("block_words", 9), c.get("line_chars", 16)
    big, normal, small = c.get("big", 100), c.get("size", 62), c.get("small", 46)
    clean = lambda t: re.sub(r"[^\w']", "", t).lower()

    blocks, cur = [], []
    for w in words:
        cur.append(w)
        if SENTENCE_END.search(w["text"]) or len(cur) >= max_words:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)

    events = []
    for bi, block in enumerate(blocks):
        marked = [i for i, w in enumerate(block) if clean(w["text"]) in emphasis]
        if not marked:
            options = [(len(clean(w["text"])), i) for i, w in enumerate(block)
                       if clean(w["text"]) not in STOP and 3 <= len(clean(w["text"])) <= 9]
            marked = [max(options)[1]] if options else []
        star = marked[0] if marked else -1

        lines: list[list[int]] = []
        for i, w in enumerate(block):
            last = lines[-1] if lines else None
            text = " ".join(block[j]["text"] for j in (last or []) + [i])
            if (last is None or i == star or star in last or len(last) >= 2 or len(text) > line_chars):
                lines.append([i])
            else:
                last.append(i)
        size_of = {}
        for ln in lines:
            n = len(" ".join(block[j]["text"] for j in ln))
            size = big if star in ln else small if n > 11 else normal
            for j in ln:
                size_of[j] = size

        block_end = (blocks[bi + 1][0]["start"] if bi + 1 < len(blocks)
                     else block[-1]["end"] + config.CAPTION_TAIL_SECONDS)
        for k, w in enumerate(block):
            shown = []
            for ln in lines:
                said = [block[j]["text"] for j in ln if j <= k]
                if said:
                    shown.append(f"{{\\fs{size_of[ln[0]]}}}" + _escape(fix_words(" ".join(said)).upper()))
            end = block[k + 1]["start"] if k + 1 < len(block) else block_end
            events.append((w["start"], end, r"\N".join(shown)))
    return events


def write_captions(words: list[dict], recipe: dict, brand: dict, out: Path, hook_text: str = "",
                   emphasis: list[str] | None = None) -> Path:
    """One ASS file with the recipe's captions (and the hook, when it's the 'pill' look)."""
    c, h = recipe["captions"], recipe["hook"]
    look = c.get("look", "caps3")
    colors = brand.get("colors", {})
    cap = colors.get("caption", {"fill": "#FFFFFF", "outline": "#000000"})
    font = font_name()
    fg = ass_color(c.get("fg", cap.get("fill", "#FFFFFF")))
    y = lambda frac, default: int(H * c.get("y", default))
    styles, events = [], []

    if look == "caps3":
        styles.append(f"Style: Caption,{config.CAPTION_FONT},{c.get('size', config.CAPTION_FONT_SIZE)},{fg},{fg},"
                      f"{ass_color(cap.get('outline', '#000000'))},&H00000000,1,0,0,0,100,100,0,0,1,"
                      f"{config.CAPTION_OUTLINE},2,2,{config.CAPTION_MARGIN_LR},{config.CAPTION_MARGIN_LR},"
                      f"{config.CAPTION_MARGIN_BOTTOM},1")
        for s, e, t in chunks_by_words(words, c.get("words", config.CAPTION_WORDS_PER_CHUNK), "upper"):
            events.append(f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Caption,,0,0,0,,{_escape(t)}")
    elif look == "word":
        styles.append(f"Style: Caption,{font},{c.get('size', 76)},{fg},{fg},&H00000000,&H80000000,1,0,0,0,"
                      f"100,100,1,0,1,4,3,5,60,60,0,1")
        pos = f"{{\\pos({W // 2},{y('y', 0.69)})}}"
        for s, e, t in chunks_by_words(words, 1, "upper"):
            events.append(f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Caption,,0,0,0,,{pos}{_escape(t.strip('.,!?'))}")
    elif look == "plain":
        margin = c.get("margin", 150)
        styles.append(f"Style: Caption,{font},{c.get('size', 52)},{fg},{fg},&H00000000,&H90000000,1,0,0,0,"
                      f"100,100,0,0,1,0,3,5,{margin},{margin},0,1")
        pos = f"{{\\pos({W // 2},{y('y', 0.75)})}}"
        for s, e, t in chunks_by_words(words, c.get("words", 10), c.get("case", "as_said")):
            events.append(f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Caption,,0,0,0,,{pos}{_escape(t)}")
    elif look == "pill":
        bg = ass_color(c.get("bg", "#3A3A3A")).replace("&H00", "&H30", 1)
        styles.append(f"Style: Caption,{font},{c.get('size', 34)},{fg},{fg},{bg},{bg},1,0,0,0,"
                      f"100,100,0,0,3,10,0,5,200,200,0,1")
        pos = f"{{\\pos({W // 2},{y('y', 0.68)})}}"
        for s, e, t in chunks_by_words(words, c.get("words", 5), c.get("case", "as_said")):
            events.append(f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Caption,,0,0,0,,{pos}{_escape(t)}")
    elif look == "stack":
        styles.append(f"Style: Caption,{font},{c.get('size', 62)},{fg},{fg},&H00000000,&HA0000000,1,0,0,0,"
                      f"100,100,0,0,1,0,2,7,0,0,0,1")
        pos = f"{{\\pos({int(W * c.get('x', 0.11))},{y('y', 0.56)})}}"
        emph = {re.sub(r"[^\w']", "", e).lower() for e in (emphasis or [])}
        for s, e, t in stack_events(words, emph, c):
            events.append(f"Dialogue: 0,{ass_ts(s)},{ass_ts(e)},Caption,,0,0,0,,{pos}{t}")
    else:
        raise ValueError(f"unknown caption look '{look}'")

    if h.get("look") == "pill" and hook_text:
        hook = colors.get("hook", {"bg": "#000000", "fg": "#FFFFFF"})
        styles.append(f"Style: Hook,{font},{h.get('size', config.HOOK_FONT_SIZE)},{ass_color(hook['fg'])},"
                      f"{ass_color(hook['fg'])},{ass_color(hook['bg'])},{ass_color(hook['bg'])},1,0,0,0,100,100,"
                      f"0,0,3,18,0,8,{config.HOOK_MARGIN_SIDES},{config.HOOK_MARGIN_SIDES},{config.HOOK_MARGIN_TOP},1")
        until = hook_until(recipe, words)
        events.insert(0, f"Dialogue: 1,{ass_ts(0)},{ass_ts(until)},Hook,,0,0,0,,{_escape(hook_text.upper())}")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out


def hook_until(recipe: dict, words: list[dict]) -> float:
    """When the hook leaves the screen: a number of seconds, or 'all' for the whole Reel."""
    seconds = recipe["hook"].get("seconds", config.HOOK_SECONDS)
    if seconds == "all":
        return (words[-1]["end"] + config.CAPTION_TAIL_SECONDS) if words else 3600.0
    return float(seconds)


# ---------- box hook (drawn with Pillow) ----------

def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=font) > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def hook_boxes_png(lines: list[str], recipe: dict, out: Path) -> Path:
    """Maria's hook: each line Claude gives gets its own white rounded box, centered, stacked.

    The first line is the big one (wrapping inside its box if long); later lines are smaller,
    like her "this is partially how:" tag under the main claim.
    """
    from PIL import Image, ImageDraw, ImageFont  # imported late: only box hooks need Pillow

    h = recipe["hook"]
    fg, bg = h.get("fg", "#000000"), h.get("bg", "#FFFFFF")
    sizes = [h.get("size", 62)] + [h.get("second_size", 36)] * (len(lines) - 1)
    path = font_file()
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = int(H * h.get("y", 0.44))
    pad_x, pad_y, gap = 26, 14, 30
    for text, size in zip(lines, sizes):
        font = ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)
        wrapped = _wrap(draw, _cased(text.strip(), h.get("case", "as_written")), font, int(W * 0.78))
        line_h = int(size * 1.18)
        width = max(draw.textlength(t, font=font) for t in wrapped)
        box_w, box_h = int(width + 2 * pad_x), line_h * len(wrapped) + 2 * pad_y
        x0 = (W - box_w) // 2
        draw.rounded_rectangle((x0, y, x0 + box_w, y + box_h), radius=int(size * 0.38), fill=bg)
        for i, t in enumerate(wrapped):
            tw = draw.textlength(t, font=font)
            draw.text(((W - tw) / 2, y + pad_y + i * line_h + line_h / 2), t, font=font, fill=fg, anchor="lm")
        y += box_h + gap
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
