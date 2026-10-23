"""A small password-protected web page for testing the agent.

Pick a client and a video, press Upload. The video is edited in the background
(one at a time) and the draft shows up on the same page to watch or download.

Password: set APP_PASSWORD (a Railway variable). The browser asks for it once;
any username works. Without APP_PASSWORD the page refuses to open.
"""

import asyncio
import html
import json
import os
import queue
import re
import secrets
import shutil
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import config

JOBS_DIR = config.DATA_DIR / "jobs"
UPLOADS_DIR = config.DATA_DIR / "uploads"
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "2000"))
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv"}
JOB_ID = re.compile(r"^[0-9a-f]{12}$")

basic = HTTPBasic(realm="Content hub agent")
_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()


# ---------- password ----------

def require_password(creds: HTTPBasicCredentials = Depends(basic)) -> None:
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        raise HTTPException(503, "Set the APP_PASSWORD variable to use this page.")
    if not secrets.compare_digest(creds.password.encode(), expected.encode()):
        raise HTTPException(401, "Wrong password", headers={"WWW-Authenticate": 'Basic realm="Content hub agent"'})


# ---------- jobs (one JSON file each, so they survive a restart) ----------

def _job_path(job_id: str) -> Path:
    if not JOB_ID.match(job_id):
        raise HTTPException(404)
    return JOBS_DIR / f"{job_id}.json"


def load_job(job_id: str) -> dict:
    path = _job_path(job_id)
    if not path.exists():
        raise HTTPException(404)
    return json.loads(path.read_text())


def save_job(job: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = JOBS_DIR / f"{job['id']}.tmp"
        tmp.write_text(json.dumps(job, indent=2))
        tmp.replace(JOBS_DIR / f"{job['id']}.json")


def update_job(job_id: str, **changes) -> dict:
    job = load_job(job_id)
    job.update(changes)
    save_job(job)
    return job


def all_jobs() -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    jobs = [json.loads(p.read_text()) for p in JOBS_DIR.glob("*.json")]
    return sorted(jobs, key=lambda j: j["created"], reverse=True)


def list_clients() -> list[str]:
    if not config.CLIENTS_DIR.exists():
        return []
    return sorted(p.name for p in config.CLIENTS_DIR.iterdir() if (p / "brand_kit.json").exists())


def safe_filename(name: str) -> str:
    """Keep the words (the filename is the hook), drop anything risky."""
    name = Path(name or "video.mp4").name
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    stem = re.sub(r"[^\w\s\-',.!?&()]", "", stem).strip()[:120] or "video"
    return stem + ext


# ---------- the background worker: one video at a time ----------

def run_job(job_id: str) -> None:
    from .agent import edit_video  # late import: the page loads even if the SDK has a problem

    job = update_job(job_id, status="working", started=time.time())
    log_lines: list[str] = []

    def log(line: str) -> None:
        log_lines.append(line.strip())
        update_job(job_id, log=log_lines[-20:])

    try:
        result = asyncio.run(edit_video(Path(job["video"]), job["client"], log=log))
        draft = Path(result["draft"])
        post_file = draft.parent / "post.json"
        post = json.loads(post_file.read_text()) if post_file.exists() else {}
        update_job(job_id, status="done", draft=str(draft), post=post,
                   cost_usd=result.get("cost_usd"), finished=time.time())
    except Exception as err:
        traceback.print_exc()
        update_job(job_id, status="failed", error=str(err)[:1500], finished=time.time())


def _worker() -> None:
    while True:
        job_id = _queue.get()
        try:
            run_job(job_id)
        finally:
            _queue.task_done()


@asynccontextmanager
async def lifespan(app):
    start_worker()
    yield


def start_worker() -> None:
    # Anything left "working" from before a restart will never finish; say so.
    for job in all_jobs():
        if job["status"] == "working":
            update_job(job["id"], status="failed", error="The server restarted while this was being edited. Upload it again.")
        elif job["status"] == "queued":
            _queue.put(job["id"])
    threading.Thread(target=_worker, daemon=True).start()


# ---------- routes ----------

app = FastAPI(title="Content hub agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/upload", dependencies=[Depends(require_password)])
def upload(video: UploadFile = File(...), client: str = Form(...)):
    if client not in list_clients():
        raise HTTPException(400, f"Unknown client '{client}'")
    filename = safe_filename(video.filename)
    if Path(filename).suffix.lower() not in VIDEO_EXTS:  # .MP4 / .MOV from phones and cameras are fine
        raise HTTPException(400, "Please upload an .mp4, .mov, .m4v or .mkv video")

    job_id = uuid.uuid4().hex[:12]
    dest = UPLOADS_DIR / job_id / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit = MAX_UPLOAD_MB * 1024 * 1024
    written = 0
    with dest.open("wb") as out:
        while chunk := video.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                shutil.rmtree(dest.parent, ignore_errors=True)
                raise HTTPException(413, f"Video is over {MAX_UPLOAD_MB} MB")
            out.write(chunk)

    save_job({"id": job_id, "client": client, "filename": filename, "video": str(dest),
              "status": "queued", "created": time.time(), "log": []})
    _queue.put(job_id)
    return RedirectResponse("/", status_code=303)


@app.get("/api/jobs", dependencies=[Depends(require_password)])
def jobs_json():
    return JSONResponse([{k: j.get(k) for k in ("id", "status")} for j in all_jobs()])


@app.get("/jobs/{job_id}/video", dependencies=[Depends(require_password)])
def job_video(job_id: str, download: int = 0):
    job = load_job(job_id)
    if job.get("status") != "done" or not Path(job["draft"]).exists():
        raise HTTPException(404)
    path = Path(job["draft"])
    if download:
        return FileResponse(path, media_type="video/mp4", filename=path.name)
    return FileResponse(path, media_type="video/mp4")


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_password)])
def home():
    clients = list_clients()
    options = "".join(f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in clients)
    jobs_html = "".join(_job_card(j) for j in all_jobs()) or '<p class="muted">No videos yet.</p>'
    key_warning = "" if os.environ.get("ANTHROPIC_API_KEY") else (
        '<p class="warn">ANTHROPIC_API_KEY is not set, so edits will fail. Add it in Railway → Variables.</p>')
    return PAGE.format(options=options, jobs=jobs_html, key_warning=key_warning, max_mb=MAX_UPLOAD_MB)


def _job_card(job: dict) -> str:
    e = html.escape
    status = job["status"]
    label = {"queued": "Waiting its turn", "working": "Editing… (usually 3-10 minutes)",
             "done": "Draft ready", "failed": "Something went wrong"}.get(status, status)
    body = ""
    if status == "done":
        post = job.get("post", {})
        tags = " ".join(post.get("hashtags", []))
        body = f"""
        <video controls preload="metadata" src="/jobs/{job['id']}/video"></video>
        <p><a class="button" href="/jobs/{job['id']}/video?download=1">Download video</a></p>
        <dl>
          <dt>Hook</dt><dd>{e(post.get('hook', ''))}</dd>
          <dt>Post caption</dt><dd class="pre">{e(post.get('post_caption', ''))}</dd>
          <dt>Hashtags</dt><dd>{e(tags)}</dd>
          <dt>Why this section</dt><dd>{e(post.get('why_this_clip', ''))}</dd>
          <dt>Clip</dt><dd>{post.get('clip_start', 0):.1f}s to {post.get('clip_end', 0):.1f}s of the original</dd>
          <dt>Claude cost</dt><dd>${(job.get('cost_usd') or 0):.2f}</dd>
        </dl>"""
    elif status == "failed":
        body = f'<p class="error">{e(job.get("error", ""))}</p>'
    if job.get("log") and status in ("working", "failed"):
        body += '<pre class="log">' + e("\n".join(job["log"])) + "</pre>"
    when = time.strftime("%b %d, %H:%M UTC", time.gmtime(job["created"]))
    return f"""
    <section class="job {status}">
      <h3>{e(job['filename'])}</h3>
      <p class="meta"><span class="status">{label}</span> · {e(job['client'])} · uploaded {when}</p>
      {body}
    </section>"""


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Content hub agent</title>
<style>
  :root {{ --bg:#f7f7f5; --card:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#e3e3de; --accent:#1F4E79; --bad:#a3271f; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#161615; --card:#21211f; --ink:#ececea; --muted:#9a9a94; --line:#33332f; --accent:#7fb0e0; --bad:#ff8a80; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }}
  main {{ max-width:720px; margin:0 auto; padding:24px 16px 64px; }}
  h1 {{ font-size:1.5rem; margin:0 0 4px; }}
  h3 {{ margin:0 0 4px; font-size:1.05rem; word-break:break-word; }}
  .muted, .meta {{ color:var(--muted); font-size:.92rem; margin:0 0 12px; }}
  form, .job {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin:16px 0; }}
  label {{ display:block; font-weight:600; margin:10px 0 4px; }}
  select, input[type=file] {{ width:100%; font:inherit; padding:8px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--ink); }}
  button, .button {{ display:inline-block; margin-top:14px; padding:10px 18px; border:0; border-radius:8px; background:var(--accent); color:#fff; font:inherit; font-weight:600; text-decoration:none; cursor:pointer; }}
  button:disabled {{ opacity:.6; cursor:wait; }}
  progress {{ width:100%; margin-top:12px; }}
  video {{ width:100%; max-height:70vh; background:#000; border-radius:8px; }}
  dl {{ margin:12px 0 0; }} dt {{ font-weight:600; margin-top:8px; }} dd {{ margin:0; }}
  .pre {{ white-space:pre-wrap; }}
  .status {{ font-weight:600; color:var(--ink); }}
  .error, .warn {{ color:var(--bad); }}
  .log {{ white-space:pre-wrap; font-size:.85rem; color:var(--muted); background:var(--bg); padding:8px; border-radius:8px; max-height:200px; overflow:auto; }}
</style></head>
<body><main>
  <h1>Content hub agent</h1>
  <p class="muted">Upload a raw talking video. Claude picks the best 30-60 seconds, writes the hook and caption, and makes a vertical draft with captions and the logo. Nothing is posted anywhere.</p>
  {key_warning}
  <form id="upload" method="post" action="/upload" enctype="multipart/form-data">
    <label for="client">Client brand kit</label>
    <select id="client" name="client">{options}</select>
    <label for="video">Video (.mp4 or .mov, any capitalization, up to {max_mb} MB)</label>
    <input id="video" name="video" type="file" accept="video/*,.mov,.mp4,.m4v,.mkv,.MOV,.MP4,.M4V,.MKV" required>
    <p class="muted">Tip: name the file after the hook, like "Why your knee still hurts.mov".</p>
    <button id="go" type="submit">Upload and edit</button>
    <progress id="bar" max="100" value="0" hidden></progress>
  </form>
  <h2>Drafts</h2>
  {jobs}
</main>
<script>
  let uploading = false;
  const form = document.getElementById('upload');
  form.addEventListener('submit', (ev) => {{
    ev.preventDefault();
    const bar = document.getElementById('bar'), go = document.getElementById('go');
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload');
    xhr.upload.onprogress = (e) => {{ if (e.lengthComputable) bar.value = 100 * e.loaded / e.total; }};
    xhr.onload = () => {{ uploading = false;
      if (xhr.status < 400) location.reload(); else {{ alert('Upload failed: ' + xhr.responseText); go.disabled = false; bar.hidden = true; }} }};
    xhr.onerror = () => {{ uploading = false; alert('Upload failed. Check your connection and try again.'); go.disabled = false; bar.hidden = true; }};
    uploading = true; go.disabled = true; go.textContent = 'Uploading…'; bar.hidden = false;
    xhr.send(new FormData(form));
  }});
  // While something is waiting or editing, check every 10 seconds and refresh when it changes.
  let last = null;
  setInterval(async () => {{
    if (uploading) return;
    const busy = document.querySelector('.job.queued, .job.working');
    if (!busy) return;
    const r = await fetch('/api/jobs'); if (!r.ok) return;
    const now = JSON.stringify(await r.json());
    if (last !== null && now !== last) location.reload();
    last = now;
  }}, 10000);
</script>
</body></html>
"""
