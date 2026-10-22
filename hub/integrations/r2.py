"""STUB: Cloudflare R2 (S3-compatible) storage for raw and finished video.

Raw client footage is too big for a Railway volume long term and over Base44's 100 MB
upload cap, so after the Drive pilot, uploads should go straight to R2 with a
presigned URL, and the worker reads/writes there.

Needs: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET. Library: boto3.
"""

from pathlib import Path


def download(key: str, dest: Path) -> Path:
    raise NotImplementedError("R2 not set up yet")


def upload(path: Path, key: str) -> str:
    raise NotImplementedError("R2 not set up yet")
