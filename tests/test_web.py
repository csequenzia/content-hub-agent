"""The upload page, with the agent swapped for a fake so no API key is needed."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import agent, config, web

AUTH = ("tester", "s3cret")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    monkeypatch.setattr(web, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(web, "UPLOADS_DIR", tmp_path / "uploads")
    draft = tmp_path / "drafts" / "d1" / "clip - first draft.mp4"
    draft.parent.mkdir(parents=True)
    draft.write_bytes(b"fake mp4")
    (draft.parent / "post.json").write_text(
        '{"hook": "Stop icing your knee", "post_caption": "Ice is not a plan.", "hashtags": ["#pt"],'
        ' "why_this_clip": "best opener", "clip_start": 3, "clip_end": 41}')

    async def fake_edit(video, client_id, log=print):
        assert Path(video).exists() and client_id == "sample-clinic"
        log("picked the knee section")
        return {"draft": draft, "cost_usd": 0.12}

    monkeypatch.setattr(agent, "edit_video", fake_edit)
    with TestClient(web.app) as c:
        yield c


def wait_for(client, status, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        jobs = client.get("/api/jobs", auth=AUTH).json()
        if jobs and jobs[0]["status"] == status:
            return jobs[0]
        time.sleep(0.1)
    raise AssertionError(f"job never reached {status}: {jobs}")


def test_password_required(client):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("x", "wrong")).status_code == 401
    assert client.get("/", auth=AUTH).status_code == 200
    assert client.get("/health").status_code == 200  # Railway health check needs no password


def test_no_password_set_means_locked(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD")
    assert client.get("/", auth=AUTH).status_code == 503


def test_upload_runs_and_shows_draft(client):
    r = client.post("/upload", auth=AUTH, data={"client": "sample-clinic"},
                    files={"video": ("Why your knee still hurts.mov", b"raw video bytes", "video/quicktime")},
                    follow_redirects=False)
    assert r.status_code == 303
    job = wait_for(client, "done")
    page = client.get("/", auth=AUTH).text
    assert "Why your knee still hurts.mov" in page
    assert "Stop icing your knee" in page and "Draft ready" in page
    video = client.get(f"/jobs/{job['id']}/video?download=1", auth=AUTH)
    assert video.status_code == 200 and video.content == b"fake mp4"
    assert "attachment" in video.headers["content-disposition"]


def test_rejects_non_video_and_unknown_client(client):
    bad = client.post("/upload", auth=AUTH, data={"client": "sample-clinic"},
                      files={"video": ("notes.txt", b"hi", "text/plain")})
    assert bad.status_code == 400
    bad = client.post("/upload", auth=AUTH, data={"client": "nobody"},
                      files={"video": ("a.mp4", b"hi", "video/mp4")})
    assert bad.status_code == 400


def test_failed_edit_is_shown(client, monkeypatch):
    async def broken(video, client_id, log=print):
        raise RuntimeError("Invalid API key")
    monkeypatch.setattr(agent, "edit_video", broken)
    client.post("/upload", auth=AUTH, data={"client": "sample-clinic"},
                files={"video": ("a.mp4", b"x", "video/mp4")})
    wait_for(client, "failed")
    assert "Invalid API key" in client.get("/", auth=AUTH).text


def test_bad_job_ids_are_404(client):
    assert client.get("/jobs/../../etc/video", auth=AUTH).status_code == 404
    assert client.get("/jobs/zzzzzzzzzzzz/video", auth=AUTH).status_code == 404


def test_filename_keeps_the_hook():
    assert web.safe_filename("../../Why your knee still hurts?.MOV") == "Why your knee still hurts?.mov"
    assert web.safe_filename("<script>.mp4") == "script.mp4"
