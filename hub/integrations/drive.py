"""STUB: Google Drive, the handoff folder for the pilot.

Greg's Base44 app already creates, per client, a Drive folder in "SSHC client videos"
with subfolders: "upload your videos here", "content plan", "scripts to film",
"ready to post", "brand kit". The worker should:
  1. pull_new_uploads: list each client's "upload your videos here" folder, download
     files it has not seen into inbox/<client-id>/ (record Drive file ids in the ledger).
  2. push_draft: upload the draft folder (mp4 + post.json) to a "first draft" subfolder
     (create it, or reuse "ready to post" if Greg prefers).
  3. pull_brand_kit: read the client's "brand kit" folder into clients/<client-id>/.

Needs: a Google service account with access to the "SSHC client videos" folder
(GOOGLE_SERVICE_ACCOUNT_JSON, DRIVE_ROOT_FOLDER_ID). Library: google-api-python-client.
"""

from pathlib import Path

ENABLED = False  # TODO: flip once GOOGLE_SERVICE_ACCOUNT_JSON is set


def pull_new_uploads(inbox: Path) -> list[Path]:
    if not ENABLED:
        return []
    raise NotImplementedError("Drive download not built yet")


def push_draft(client_id: str, draft_folder: Path) -> None:
    if not ENABLED:
        print(f"  [drive stub] would upload {draft_folder.name} to {client_id}/first draft")
        return
    raise NotImplementedError("Drive upload not built yet")


def pull_brand_kit(client_id: str) -> None:
    if not ENABLED:
        return
    raise NotImplementedError("Drive brand kit sync not built yet")
