"""Edit recipes: how to cut and dress a Reel so it looks like one particular reference video.

Content Studio's talking-head cards are each modelled on one of Maria Wendt's reels, and
every one of her edits is different (word-stack captions, a boxed hook pinned on screen,
plain Instagram captions, cuts between a wide and a close shot...). A recipe is that
reel's edit written down as data the renderer can follow, plus notes for Claude:

    recipes/<template id>.json      e.g. recipes/R09.json for "The Big Reveal"

Fields (all optional except name; anything left out falls back to DEFAULT):
  name, source            the reference reel and where to watch it
  length.min / .max       seconds the finished Reel should run
  hook                    look: "pill" | "boxes" | "none"; seconds (a number, or "all");
                          y (0-1, top of the hook), size, second_size, fg, bg, case
  captions                look: "caps3" | "word" | "plain" | "pill" | "stack"; y, size, words,
                          fg, bg, case ("upper" | "as_said")
  shots                   [{"at": 0-1 of the Reel, "zoom": 1.0-2.0}], the default camera plan
                          when Claude does not give one; zoom 1 is the full frame
  focus                   {"x", "y"} 0-1, the point a zoom closes in on (the face)
  pauses.max_gap          gaps between words longer than this (seconds) are cut out
  edit_notes              plain-language notes for Claude: beats, where the cuts go, what to keep
"""

import copy
import json
import re
from pathlib import Path

from . import config

RECIPES_DIR = config.ROOT / "recipes"

# The house style from Greg's pipelines, used when a video has no recipe.
DEFAULT = {
    "name": "House style",
    "length": {"min": config.MIN_CLIP_SECONDS, "max": config.MAX_CLIP_SECONDS},
    "hook": {"look": "pill", "seconds": config.HOOK_SECONDS},
    "captions": {"look": "caps3"},
    "shots": [],
    "focus": {"x": 0.5, "y": 0.33},
    "pauses": {"max_gap": None},
    "edit_notes": "",
}

ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def load_recipe(template: str | None) -> dict:
    """The recipe for a template id, merged over DEFAULT. Unknown or missing ids get DEFAULT."""
    recipe = copy.deepcopy(DEFAULT)
    if template and ID.match(template):
        path = RECIPES_DIR / f"{template}.json"
        if path.exists():
            _merge(recipe, json.loads(path.read_text(encoding="utf-8")))
            recipe["template"] = template
    return recipe


def available() -> list[str]:
    return sorted(p.stem for p in RECIPES_DIR.glob("*.json")) if RECIPES_DIR.exists() else []


def _merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def describe(recipe: dict) -> str:
    """The recipe as Claude reads it: notes first, then the settings the renderer will use."""
    settings = {k: v for k, v in recipe.items() if k not in ("edit_notes",)}
    notes = recipe.get("edit_notes") or "No notes; follow the settings."
    return f"{notes}\n\nRenderer settings (already applied for you):\n{json.dumps(settings, indent=1)}"
