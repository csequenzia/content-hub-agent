import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hub import config


def fake_transcript(duration: float = 70.0) -> dict:
    """One 5-second sentence of ten words every 5 seconds."""
    segments = []
    t = 0.0
    n = 0
    while t + 5 <= duration:
        words = []
        for i in range(10):
            text = "patience" if (n == 1 and i == 2) else f"word{n}_{i}"
            words.append({"start": round(t + i * 0.5, 2), "end": round(t + i * 0.5 + 0.4, 2), "word": text})
        segments.append({"start": t, "end": t + 4.9, "text": " ".join(w["word"] for w in words) + ".",
                         "words": words})
        t += 5
        n += 1
    return {"duration": duration, "segments": segments}


@pytest.fixture
def transcript():
    return fake_transcript()


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(config, "WORK_DIR", tmp_path / "work")
    return tmp_path


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("video") / "Why your knee still hurts.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=70",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=70", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out
