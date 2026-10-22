"""The trigger: check each client's upload folder and edit anything new.

Today it watches local folders: inbox/<client-id>/<video>. Once Drive access is set
up, integrations/drive.py will download new uploads into the same inbox and push
finished drafts back to the client's "first draft" folder.
"""

import asyncio
import json
import time

from . import config
from .integrations import drive, notify

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv"}
LEDGER = config.WORK_DIR / "processed.json"


def _load_ledger() -> dict:
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else {}


def _save_ledger(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=2))


def new_uploads() -> list[tuple[str, "Path"]]:
    ledger = _load_ledger()
    found = []
    if not config.INBOX_DIR.exists():
        return found
    for client_dir in sorted(p for p in config.INBOX_DIR.iterdir() if p.is_dir()):
        for video in sorted(client_dir.iterdir()):
            key = f"{client_dir.name}/{video.name}"
            if video.suffix.lower() in VIDEO_EXTS and key not in ledger:
                found.append((client_dir.name, video))
    return found


def scan_once() -> int:
    from .agent import edit_video  # imported here so `render`/`transcribe` work without the SDK

    drive.pull_new_uploads(config.INBOX_DIR)   # stub: does nothing until Drive is connected
    ledger = _load_ledger()
    done = 0
    for client_id, video in new_uploads():
        key = f"{client_id}/{video.name}"
        print(f"=== editing {key}")
        try:
            result = asyncio.run(edit_video(video, client_id))
        except Exception as err:  # one bad video must not stop the others
            print(f"  failed: {err}")
            ledger[key] = {"status": "failed", "error": str(err)[:500]}
            _save_ledger(ledger)
            continue
        ledger[key] = {"status": "drafted", "draft": str(result["draft"]), "cost_usd": result.get("cost_usd")}
        _save_ledger(ledger)
        drive.push_draft(client_id, result["draft"].parent)   # stub
        notify.draft_ready(client_id, result["draft"].parent)  # stub
        print(f"  draft: {result['draft']}")
        done += 1
    return done


def watch_forever() -> None:
    print(f"watching {config.INBOX_DIR} every {config.POLL_MINUTES} min")
    while True:
        scan_once()
        time.sleep(config.POLL_MINUTES * 60)
