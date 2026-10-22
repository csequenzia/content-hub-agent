"""Tell someone a draft is ready. Prints for now; later GHL or Base44 (see ghl.py, base44.py)."""

from pathlib import Path


def draft_ready(client_id: str, draft_folder: Path) -> None:
    print(f"  [notify stub] draft ready for review: {client_id}/{draft_folder.name}")
