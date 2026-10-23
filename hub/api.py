"""The API apps use to send videos and read drafts: Greg's Base44 app now, an internal app later.

Every call needs the header  Authorization: Bearer <HUB_API_TOKEN>.
Call it from the app's server side (a Base44 backend function), never from browser code,
so the token stays secret. docs/API.md has the full walkthrough.

  POST /api/v1/uploads              get a link to put a raw video straight into R2
  POST /api/v1/videos               "new video": queue an edit (from R2, or from a file URL)
  GET  /api/v1/videos/{id}          status, and the draft link once it is ready
  GET  /api/v1/videos?client_id=    list
  POST /api/v1/videos/{id}/review   approve, or ask for changes

Status: ready_to_edit -> editing -> draft_ready -> approved | changes_requested
        (or failed). With a callback_url, the app is told when a draft is ready or failed.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import web
from .integrations import r2

router = APIRouter(prefix="/api/v1")

STATUS = {"queued": "ready_to_edit", "working": "editing", "done": "draft_ready", "failed": "failed"}
KEY = re.compile(r"^raw/[\w\-]+/[0-9a-f]{12}/[^/]+$")


def require_token(authorization: str = Header("")) -> None:
    expected = os.environ.get("HUB_API_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Set the HUB_API_TOKEN variable to use the API.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, "Missing or wrong API token")


def _client_ok(client_id: str) -> None:
    if client_id not in web.list_clients():
        raise HTTPException(400, f"Unknown client '{client_id}'")


def _video_name(filename: str) -> str:
    name = web.safe_filename(filename)
    if Path(name).suffix.lower() not in web.VIDEO_EXTS:
        raise HTTPException(400, "filename must end in .mp4, .mov, .m4v or .mkv")
    return name


# ---------- what the app sends ----------

class UploadRequest(BaseModel):
    client_id: str
    filename: str = Field(description="The raw file's name. Keep the hook in it, like 'Why your knee still hurts.mov'")
    content_type: str = "video/mp4"


class NewVideo(BaseModel):
    client_id: str
    mode: Literal["reel", "course"] = "reel"
    video_key: str | None = Field(None, description="Key from POST /uploads, after the upload finished")
    video_url: str | None = Field(None, description="Or an https link to the file (fine for small files)")
    filename: str | None = Field(None, description="Needed with video_url")
    external_id: str | None = Field(None, description="The app's own id for this video, echoed back")
    callback_url: str | None = Field(None, description="https URL we POST to when the draft is ready or failed")


class Review(BaseModel):
    decision: Literal["approved", "changes_requested"]
    note: str = ""
    by: str = ""


# ---------- routes ----------

@router.post("/uploads", dependencies=[Depends(require_token)])
def new_upload(req: UploadRequest):
    _client_ok(req.client_id)
    if not r2.configured():
        raise HTTPException(503, "R2 storage is not set up (R2_* variables). Send video_url instead.")
    key = f"raw/{req.client_id}/{uuid.uuid4().hex[:12]}/{_video_name(req.filename)}"
    return {"video_key": key, "upload_url": r2.upload_link(key, req.content_type), "method": "PUT",
            "headers": {"Content-Type": req.content_type}, "expires_in": r2.UPLOAD_LINK_SECONDS}


@router.post("/videos", status_code=201, dependencies=[Depends(require_token)])
def new_video(req: NewVideo):
    _client_ok(req.client_id)
    if bool(req.video_key) == bool(req.video_url):
        raise HTTPException(400, "Send exactly one of video_key or video_url")
    for url in (req.video_url, req.callback_url):
        if url and not url.startswith("https://"):
            raise HTTPException(400, "Links must start with https://")

    if req.video_key:
        if not KEY.match(req.video_key) or not req.video_key.startswith(f"raw/{req.client_id}/"):
            raise HTTPException(400, "video_key must be one returned by POST /uploads for this client")
        if not r2.configured():
            raise HTTPException(503, "R2 storage is not set up")
        stored = r2.size(req.video_key)
        if not stored:
            raise HTTPException(409, "Nothing is uploaded at video_key yet. Finish the upload first.")
        if stored > web.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"Video is over {web.MAX_UPLOAD_MB} MB")
        filename = req.video_key.rsplit("/", 1)[1]
        source = {"r2_key": req.video_key}
    else:
        filename = _video_name(req.filename or Path(req.video_url.split("?")[0]).name)
        source = {"url": req.video_url}

    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "client": req.client_id, "mode": req.mode, "filename": filename,
           "video": str(web.UPLOADS_DIR / job_id / filename), "source": source,
           "external_id": req.external_id, "callback_url": req.callback_url, "via": "api",
           "status": "queued", "created": time.time(), "log": []}
    web.save_job(job)
    web.enqueue(job_id)
    return describe(job)


@router.get("/videos", dependencies=[Depends(require_token)])
def list_videos(client_id: str | None = None, limit: int = 50):
    jobs = [j for j in web.all_jobs() if client_id is None or j["client"] == client_id]
    return {"videos": [describe(j) for j in jobs[:max(1, min(limit, 200))]]}


@router.get("/videos/{job_id}", dependencies=[Depends(require_token)])
def get_video(job_id: str):
    return describe(web.load_job(job_id))


@router.get("/videos/{job_id}/draft", dependencies=[Depends(require_token)])
def get_draft_file(job_id: str):
    """The draft mp4 itself, for when R2 is not set up."""
    job = web.load_job(job_id)
    if job.get("status") != "done" or not Path(job["draft"]).exists():
        raise HTTPException(404, "No draft yet")
    return FileResponse(job["draft"], media_type="video/mp4", filename=Path(job["draft"]).name)


@router.post("/videos/{job_id}/review", dependencies=[Depends(require_token)])
def review(job_id: str, req: Review):
    job = web.load_job(job_id)
    if job.get("status") != "done":
        raise HTTPException(409, "Only a finished draft can be reviewed")
    job = web.update_job(job_id, review={"status": req.decision, "note": req.note, "by": req.by, "at": time.time()})
    return describe(job)


# ---------- how a job looks to the app ----------

def describe(job: dict) -> dict:
    status = STATUS.get(job["status"], job["status"])
    if status == "draft_ready" and job.get("review"):
        status = job["review"]["status"]
    out = {"id": job["id"], "status": status, "client_id": job["client"], "mode": job.get("mode", "reel"),
           "filename": job["filename"], "external_id": job.get("external_id"),
           "created_at": _iso(job["created"]), "finished_at": _iso(job.get("finished")),
           "draft": None, "review": job.get("review"), "error": job.get("error")}
    if job["status"] == "done":
        draft = {"filename": Path(job["draft"]).name, "cost_usd": job.get("cost_usd")}
        if job.get("draft_key") and r2.configured():
            draft["video_url"] = r2.download_link(job["draft_key"], draft["filename"])
            draft["video_key"] = job["draft_key"]
        else:
            draft["video_url"] = f"/api/v1/videos/{job['id']}/draft"   # same server, needs the token
        if job.get("mode") == "course":
            draft["course"] = job.get("course")
        else:
            draft["post"] = job.get("post")
        out["draft"] = draft
    return out


def _iso(ts: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


# ---------- called by the worker (web.run_job) ----------

def fetch_source(job: dict) -> Path:
    """Bring an API job's raw video onto this server before editing."""
    dest = Path(job["video"])
    if dest.exists():
        return dest
    source = job.get("source") or {}
    if "r2_key" in source:
        return r2.download(source["r2_key"], dest)
    if "url" in source:
        dest.parent.mkdir(parents=True, exist_ok=True)
        limit = web.MAX_UPLOAD_MB * 1024 * 1024
        written = 0
        with urllib.request.urlopen(source["url"], timeout=120) as resp, dest.open("wb") as out:
            while chunk := resp.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise RuntimeError(f"Video at video_url is over {web.MAX_UPLOAD_MB} MB")
                out.write(chunk)
        return dest
    raise RuntimeError("job has no video source")


def publish_draft(job: dict) -> dict:
    """Copy a finished draft to R2 (if set up) so apps can link to it. Returns fields to save on the job."""
    if not r2.configured():
        return {}
    draft = Path(job["draft"])
    key = f"drafts/{job['client']}/{job['id']}/{draft.name}"
    r2.upload(draft, key)
    post = draft.parent / "post.json"
    if post.exists():
        r2.upload(post, f"drafts/{job['client']}/{job['id']}/post.json", "application/json")
    return {"draft_key": key}


def send_callback(job: dict) -> None:
    """POST the job's status to its callback_url, signed so the app can check it came from us.

    Header X-Hub-Signature: sha256=<HMAC-SHA256 of the body, keyed with HUB_API_TOKEN>.
    Failures are logged on the job, never raised: the app can always poll instead.
    """
    url = job.get("callback_url")
    if not url:
        return
    body = json.dumps(describe(job)).encode()
    sig = hmac.new(os.environ.get("HUB_API_TOKEN", "").encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Hub-Signature": f"sha256={sig}", "User-Agent": "content-hub-agent"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20):
                web.update_job(job["id"], callback={"ok": True, "at": time.time()})
                return
        except Exception as err:  # noqa: BLE001 - any network or HTTP error
            last = str(err)
            time.sleep(2 ** attempt)
    web.update_job(job["id"], callback={"ok": False, "error": last[:300], "at": time.time()})


web.app.include_router(router)
