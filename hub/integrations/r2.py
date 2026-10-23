"""Cloudflare R2 storage (S3-compatible) for raw uploads and finished drafts.

Apps never send video through this server. They ask the API for an upload link, put
the file straight into R2 (no 100 MB limit like Base44's), then tell the API the key.
The worker downloads it, edits it, and puts the draft back in R2 under drafts/.

Needs: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
(Cloudflare dashboard -> R2 -> Manage API tokens, "Object Read & Write" on that bucket).
"""

import os
from functools import lru_cache
from pathlib import Path

UPLOAD_LINK_SECONDS = 2 * 60 * 60      # time an app has to start the upload
DOWNLOAD_LINK_SECONDS = 24 * 60 * 60   # draft links; the app gets a fresh one each time it asks


def configured() -> bool:
    return all(os.environ.get(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"))


def bucket() -> str:
    return os.environ["R2_BUCKET"]


@lru_cache(maxsize=1)
def _client():
    import boto3  # imported late: only needed when R2 is set up
    from botocore.config import Config

    endpoint = os.environ.get("R2_ENDPOINT") or f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        # Newer boto3 adds checksum fields to presigned uploads that a browser can't send; R2 doesn't need them
        config=Config(signature_version="s3v4", request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )


def upload_link(key: str, content_type: str) -> str:
    """A URL the app PUTs the raw video to, with header Content-Type: <content_type>."""
    return _client().generate_presigned_url(
        "put_object", Params={"Bucket": bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_LINK_SECONDS)


def download_link(key: str, filename: str | None = None) -> str:
    params = {"Bucket": bucket(), "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return _client().generate_presigned_url("get_object", Params=params, ExpiresIn=DOWNLOAD_LINK_SECONDS)


def size(key: str) -> int | None:
    """Bytes stored at key, or None if nothing is there (yet)."""
    from botocore.exceptions import ClientError
    try:
        return _client().head_object(Bucket=bucket(), Key=key)["ContentLength"]
    except ClientError:
        return None


def download(key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(bucket(), key, str(dest))
    return dest


def upload(path: Path, key: str, content_type: str = "video/mp4") -> str:
    _client().upload_file(str(path), bucket(), key, ExtraArgs={"ContentType": content_type})
    return key
