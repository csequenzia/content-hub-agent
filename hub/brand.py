"""Client brand kits: clients/<client-id>/brand_kit.json (+ an optional logo file).

The fields mirror what clients fill in on Greg's Base44 brand kit page (voice,
audience, offers, story, never-say list, colors, logo), plus the color slots used
by Greg's desktop pipelines (brands/<name>.json in claude-video-edits).
"""

import json
from pathlib import Path

from . import config


def load_brand(client_id: str) -> dict:
    path = config.CLIENTS_DIR / client_id / "brand_kit.json"
    if not path.exists():
        known = sorted(p.name for p in config.CLIENTS_DIR.iterdir() if p.is_dir()) if config.CLIENTS_DIR.exists() else []
        raise FileNotFoundError(f"no brand kit for '{client_id}' (have: {', '.join(known) or 'none'})")
    return json.loads(path.read_text(encoding="utf-8"))


def logo_path(client_id: str, brand: dict) -> Path | None:
    name = brand.get("logo")
    if not name:
        return None
    path = config.CLIENTS_DIR / client_id / name
    return path if path.exists() else None
