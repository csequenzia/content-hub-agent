"""Settings, read from environment variables (Railway variables in production, .env locally)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Claude
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.environ.get("CLAUDE_EFFORT", "medium")
MAX_AGENT_TURNS = int(os.environ.get("MAX_AGENT_TURNS", "20"))
MAX_BUDGET_USD = float(os.environ.get("MAX_BUDGET_USD", "2.00"))  # hard stop per video

# Transcription (faster-whisper runs on the server's CPU, no extra API key)
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

# Folders. On Railway, point DATA_DIR at a volume.
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT))
CLIENTS_DIR = Path(os.environ.get("CLIENTS_DIR", ROOT / "clients"))
INBOX_DIR = Path(os.environ.get("INBOX_DIR", DATA_DIR / "inbox"))
DRAFTS_DIR = Path(os.environ.get("DRAFTS_DIR", DATA_DIR / "drafts"))
WORK_DIR = Path(os.environ.get("WORK_DIR", DATA_DIR / "work"))
FONTS_DIR = ROOT / "fonts"

# How often the watcher checks for new uploads
POLL_MINUTES = int(os.environ.get("POLL_MINUTES", "30"))

# Clip length rules for a Reel
MIN_CLIP_SECONDS = 30
MAX_CLIP_SECONDS = 60

# Output format (matches Greg's validated Reels pipelines)
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
FPS = 30
VIDEO_CODEC = os.environ.get("VIDEO_CODEC", "libx264")
VIDEO_CRF = os.environ.get("VIDEO_CRF", "20")
VIDEO_PRESET = os.environ.get("VIDEO_PRESET", "veryfast")

# Look. Greg's pipelines use Arial Black; drop ariblk.ttf into fonts/ and set
# CAPTION_FONT="Arial Black" to match exactly. DejaVu Sans Bold ships in the Docker image.
CAPTION_FONT = os.environ.get("CAPTION_FONT", "DejaVu Sans")
CAPTION_FONT_SIZE = 80
CAPTION_OUTLINE = 6
CAPTION_MARGIN_LR = 110
CAPTION_MARGIN_BOTTOM = 440    # y ≈ 1480, same as Talking Head Videos
CAPTION_WORDS_PER_CHUNK = 3
CAPTION_TAIL_SECONDS = 0.5

HOOK_FONT_SIZE = 72
HOOK_MARGIN_TOP = 280          # just below the Reels top safe zone (250)
HOOK_SECONDS = 4.0
HOOK_MARGIN_SIDES = 220        # keeps the hook pill clear of the logo in the top-right corner

LOGO_WIDTH = 150
LOGO_MARGIN = 50
LOGO_TOP = 260                 # inside the Reels safe area

# Whisper mishears healthcare words. Same fixes as Greg's Podcast Style Clips pipeline.
CAPTION_REPLACEMENTS = {
    "patience": "patients",
    "dietician": "dietitian",
    "dieticians": "dietitians",
    "cloud code": "Claude Code",
}
