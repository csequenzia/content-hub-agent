"""The app-facing API (hub/api.py), with R2 played by a local moto S3 server and the agent faked."""

import hashlib
import hmac
import io
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hub import agent, api, web
from hub.integrations import r2

TOKEN = "test-token-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def s3_server():
    moto_server = pytest.importorskip("moto.server")
    for var in ("NO_PROXY", "no_proxy"):   # reach the local server directly even behind a proxy
        os.environ[var] = ",".join(filter(None, [os.environ.get(var), "127.0.0.1", "localhost"]))
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def edits(tmp_path, monkeypatch):
    """Fake agent: records the raw bytes it was given and returns a small draft."""
    seen = []

    async def fake_edit(video, client_id, log=print):
        seen.append(Path(video).read_bytes())
        draft = tmp_path / "drafts" / client_id / "d" / "clip - first draft.mp4"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_bytes(b"DRAFT MP4")
        (draft.parent / "post.json").write_text('{"hook": "Stop icing your knee"}')
        return {"draft": draft, "cost_usd": 0.1}

    monkeypatch.setattr(agent, "edit_video", fake_edit)
    return seen


@pytest.fixture
def client(tmp_path, monkeypatch, edits):
    monkeypatch.setenv("HUB_API_TOKEN", TOKEN)
    monkeypatch.setenv("APP_PASSWORD", "pw")
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(web, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(web, "UPLOADS_DIR", tmp_path / "uploads")
    r2._client.cache_clear()
    with TestClient(web.app) as c:
        yield c
    r2._client.cache_clear()


@pytest.fixture
def with_r2(monkeypatch, s3_server):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", "hub-test")
    monkeypatch.setenv("R2_ENDPOINT", s3_server)
    r2._client.cache_clear()
    try:
        r2._client().create_bucket(Bucket="hub-test",   # moto wants a region; real R2 doesn't
                                   CreateBucketConfiguration={"LocationConstraint": "auto"})
    except r2._client().exceptions.BucketAlreadyOwnedByYou:
        pass


@pytest.fixture
def callbacks(monkeypatch):
    """Capture callback POSTs instead of sending them."""
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append(req)
        return io.BytesIO(b"ok")

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    return sent


def wait(client, job_id, status, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/v1/videos/{job_id}", headers=AUTH).json()
        if job["status"] == status:
            return job
        time.sleep(0.05)
    raise AssertionError(f"never reached {status}: {job}")


def test_token_required(client, monkeypatch):
    assert client.get("/api/v1/videos").status_code == 401
    assert client.get("/api/v1/videos", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/videos", headers=AUTH).status_code == 200
    monkeypatch.delenv("HUB_API_TOKEN")
    assert client.get("/api/v1/videos", headers=AUTH).status_code == 503
    # the upload page password does not open the API, and the API token does not open the page
    assert client.get("/", headers=AUTH).status_code == 401


def test_r2_upload_to_approved_draft(client, with_r2, edits, callbacks):
    up = client.post("/api/v1/uploads", headers=AUTH, json={
        "client_id": "sample-clinic", "filename": "Why your knee still hurts.MOV", "content_type": "video/quicktime"})
    assert up.status_code == 200
    up = up.json()
    assert up["video_key"].startswith("raw/sample-clinic/") and up["video_key"].endswith("/Why your knee still hurts.mov")

    early = client.post("/api/v1/videos", headers=AUTH, json={"client_id": "sample-clinic", "video_key": up["video_key"]})
    assert early.status_code == 409   # nothing uploaded yet

    put = httpx.put(up["upload_url"], content=b"RAW VIDEO", headers=up["headers"])   # what the app does
    assert put.status_code == 200

    made = client.post("/api/v1/videos", headers=AUTH, json={
        "client_id": "sample-clinic", "video_key": up["video_key"], "external_id": "base44-abc",
        "callback_url": "https://app.example/hooks/draft"})
    assert made.status_code == 201
    assert made.json()["status"] in ("ready_to_edit", "editing") and made.json()["external_id"] == "base44-abc"

    job = wait(client, made.json()["id"], "draft_ready")
    assert edits == [b"RAW VIDEO"]
    assert job["draft"]["post"] == {"hook": "Stop icing your knee"}
    assert job["draft"]["video_key"] == f"drafts/sample-clinic/{job['id']}/clip - first draft.mp4"
    assert httpx.get(job["draft"]["video_url"]).content == b"DRAFT MP4"

    # the app was told, with a signature it can check
    for _ in range(100):
        if callbacks:
            break
        time.sleep(0.05)
    req = callbacks[0]
    assert req.full_url == "https://app.example/hooks/draft"
    expected = hmac.new(TOKEN.encode(), req.data, hashlib.sha256).hexdigest()
    assert req.get_header("X-hub-signature") == f"sha256={expected}"
    assert json.loads(req.data)["status"] == "draft_ready"

    reviewed = client.post(f"/api/v1/videos/{job['id']}/review", headers=AUTH,
                           json={"decision": "approved", "by": "Greg"}).json()
    assert reviewed["status"] == "approved" and reviewed["review"]["by"] == "Greg"
    listed = client.get("/api/v1/videos?client_id=sample-clinic", headers=AUTH).json()["videos"]
    assert [v["status"] for v in listed] == ["approved"]
    page = client.get("/", auth=("x", "pw")).text
    assert "Approved" in page and "from the app" in page


def test_video_url_without_r2(client, edits, callbacks, monkeypatch):
    def fake_urlopen(req, timeout=None):
        if isinstance(req, str):            # the video download
            assert req == "https://files.base44.app/raw/clip.mp4?sig=1"
            return io.BytesIO(b"SMALL VIDEO")
        callbacks.append(req)
        return io.BytesIO(b"ok")

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)
    made = client.post("/api/v1/videos", headers=AUTH, json={
        "client_id": "sample-clinic", "mode": "reel", "video_url": "https://files.base44.app/raw/clip.mp4?sig=1"})
    assert made.status_code == 201
    job = wait(client, made.json()["id"], "draft_ready")
    assert edits == [b"SMALL VIDEO"] and job["filename"] == "clip.mp4"
    assert job["draft"]["video_url"] == f"/api/v1/videos/{job['id']}/draft"
    assert client.get(job["draft"]["video_url"], headers=AUTH).content == b"DRAFT MP4"
    assert client.get(job["draft"]["video_url"]).status_code == 401
    assert not callbacks   # no callback_url given


def test_failed_edit_is_reported(client, callbacks, monkeypatch):
    async def broken(video, client_id, log=print):
        raise RuntimeError("Invalid API key")

    monkeypatch.setattr(agent, "edit_video", broken)
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda req, timeout=None: (
        io.BytesIO(b"v") if isinstance(req, str) else callbacks.append(req) or io.BytesIO(b"ok")))
    made = client.post("/api/v1/videos", headers=AUTH, json={
        "client_id": "sample-clinic", "video_url": "https://x.example/a.mp4", "callback_url": "https://app.example/h"})
    job = wait(client, made.json()["id"], "failed")
    assert "Invalid API key" in job["error"]
    for _ in range(100):
        if callbacks:
            break
        time.sleep(0.05)
    assert json.loads(callbacks[0].data)["status"] == "failed"


def test_bad_requests(client, with_r2):
    def post(body):
        return client.post("/api/v1/videos", headers=AUTH, json={"client_id": "sample-clinic", **body}).status_code

    assert post({}) == 400                                                              # no source
    assert post({"video_key": "raw/sample-clinic/0123456789ab/a.mp4", "video_url": "https://x/a.mp4"}) == 400
    assert post({"video_url": "http://x.example/a.mp4"}) == 400                          # not https
    assert post({"video_url": "https://x.example/a.mp4", "callback_url": "http://x"}) == 400
    assert post({"video_url": "https://x.example/notes.txt"}) == 400                      # not a video
    assert post({"video_key": "raw/other-client/0123456789ab/a.mp4"}) == 400              # someone else's key
    assert post({"video_key": "../../etc/passwd"}) == 400
    assert post({"video_url": "https://x.example/a.mp4", "mode": "movie"}) == 422
    assert client.post("/api/v1/videos", headers=AUTH, json={"client_id": "nobody", "video_url": "https://x/a.mp4"}).status_code == 400
    assert client.get("/api/v1/videos/zzzzzzzzzzzz", headers=AUTH).status_code == 404


def test_upload_link_needs_r2(client):
    r = client.post("/api/v1/uploads", headers=AUTH, json={"client_id": "sample-clinic", "filename": "a.mp4"})
    assert r.status_code == 503 and "video_url" in r.json()["detail"]


def test_review_only_after_draft(client, monkeypatch):
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b"v"))
    job = web.save_job({"id": "aaaaaaaaaaaa", "client": "sample-clinic", "filename": "a.mp4", "video": "/nope",
                        "status": "failed", "created": time.time(), "log": []})
    r = client.post("/api/v1/videos/aaaaaaaaaaaa/review", headers=AUTH, json={"decision": "approved"})
    assert r.status_code == 409 and job is None
