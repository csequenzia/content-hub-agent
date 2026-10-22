"""Command line.

  python -m hub edit <video> --client <id>                 Claude picks the clip and renders a draft
  python -m hub render <video> --client <id> --plan p.json  render a hand-written plan (no API key)
  python -m hub transcribe <video>                          print the transcript (no API key)
  python -m hub scan                                        edit every new video in inbox/ once
  python -m hub watch                                       scan every POLL_MINUTES, forever
"""

import argparse
import asyncio
import json
from pathlib import Path

from . import config, media


def main() -> None:
    parser = argparse.ArgumentParser(prog="hub", description="Content hub video editing agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("edit", help="have Claude edit one raw video")
    p.add_argument("video", type=Path)
    p.add_argument("--client", required=True)

    p = sub.add_parser("render", help="render a draft from a plan file, no Claude call")
    p.add_argument("video", type=Path)
    p.add_argument("--client", required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--transcript", type=Path, help="use this transcript.json instead of running Whisper")

    p = sub.add_parser("transcribe", help="print the numbered transcript")
    p.add_argument("video", type=Path)

    sub.add_parser("scan", help="edit every new upload once")
    sub.add_parser("watch", help="keep scanning on a timer")

    args = parser.parse_args()
    media.require_ffmpeg()

    if args.cmd == "edit":
        from .agent import edit_video
        result = asyncio.run(edit_video(args.video, args.client))
        print(f"\nDraft: {result['draft']}\nCost: ${result.get('cost_usd') or 0:.2f}")

    elif args.cmd == "render":
        from .drafts import render_draft
        from .transcribe import transcribe
        work = config.WORK_DIR / args.client / args.video.stem
        tx = json.loads(args.transcript.read_text()) if args.transcript else transcribe(args.video, work)
        out = render_draft(args.video.resolve(), args.client, tx, json.loads(args.plan.read_text()))
        print(f"Draft: {out}")

    elif args.cmd == "transcribe":
        from .transcribe import as_numbered_text, transcribe
        print(as_numbered_text(transcribe(args.video, config.WORK_DIR / "_transcripts" / args.video.stem)))

    elif args.cmd == "scan":
        from .watcher import scan_once
        print(f"{scan_once()} draft(s) made")

    elif args.cmd == "watch":
        from .watcher import watch_forever
        watch_forever()


if __name__ == "__main__":
    main()
