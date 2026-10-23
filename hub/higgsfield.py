"""Image aids for course lessons, made with the Higgsfield API.

Set HIGGSFIELD_API_KEY to "<key id>:<key secret>" (cloud.higgsfield.ai -> API keys).
Without it, lessons still render; they just have no picture beats.

The model is Recraft V4.1 by default: flat illustration with a fixed color palette and
background, which suits the course look. Change HIGGSFIELD_IMAGE_MODEL to try another
Higgsfield text-to-image endpoint that takes the same prompt + aspect_ratio fields.
"""

import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

API = "https://api.higgsfield.ai"
DONE = {"completed", "failed", "nsfw", "canceled"}


def api_key() -> str:
    return os.environ.get("HIGGSFIELD_API_KEY", "").strip()


def model() -> str:
    return os.environ.get("HIGGSFIELD_IMAGE_MODEL", "recraft/v4.1/text-to-image").strip("/")


def _request(method: str, url: str, body: dict | None = None, idempotency: str | None = None) -> dict:
    headers = {"Authorization": f"Key {api_key()}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if idempotency:
        headers["Idempotency-Key"] = idempotency
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def generate_image(prompt: str, out: Path, aspect_ratio: str = "4:3",
                   colors: list[tuple[int, int, int]] | None = None,
                   background: tuple[int, int, int] | None = None,
                   timeout: float = 300, poll: float = 3) -> Path:
    """Make one image and save it to `out` (png). Raises RuntimeError if Higgsfield refuses or fails."""
    if not api_key():
        raise RuntimeError("HIGGSFIELD_API_KEY is not set")
    body: dict = {"prompt": prompt, "aspect_ratio": aspect_ratio, "output_format": "png"}
    if model().startswith("recraft/"):
        body["resolution"] = "1k"
        if colors:
            body["colors"] = [{"rgb": list(c)} for c in colors]
        if background:
            body["background_color"] = {"rgb": list(background)}

    job = _request("POST", f"{API}/{model()}", body, idempotency=uuid.uuid4().hex)
    status_url = job.get("status_url") or f"{API}/requests/{job['request_id']}/status"
    deadline = time.monotonic() + timeout
    while job.get("status") not in DONE:
        if time.monotonic() > deadline:
            raise RuntimeError(f"Higgsfield took longer than {timeout:.0f}s")
        time.sleep(poll)
        job = _request("GET", status_url)
    if job["status"] != "completed" or not job.get("images"):
        raise RuntimeError(f"Higgsfield returned {job['status']}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(job["images"][0]["url"], timeout=120) as resp:
        out.write_bytes(resp.read())
    return out
