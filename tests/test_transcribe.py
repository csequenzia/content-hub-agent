"""Transcription plumbing, without downloading a Whisper model.

Regression: faster-whisper decodes files with PyAV, and av 19 removed the
`metadata_errors` argument it passes, so every transcription failed on Railway.
We now decode with ffmpeg and hand Whisper a ready array.
"""

import subprocess
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from hub import transcribe


def test_audio_reaches_whisper_as_an_array_not_a_file(sample_video, tmp_path, monkeypatch):
    seen = {}

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            seen["audio"] = audio
            word = SimpleNamespace(start=0.5, end=0.9, word=" Hello")
            seg = SimpleNamespace(start=0.5, end=0.9, text=" Hello.", words=[word])
            return iter([seg]), SimpleNamespace(duration=len(audio) / 16000)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    tx = transcribe.transcribe(sample_video, tmp_path / "work")

    audio = seen["audio"]
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert abs(len(audio) / 16000 - 70) < 0.5            # the whole 70 s clip, at 16 kHz
    assert 0.05 < float(np.abs(audio).max()) <= 1.0       # real signal, scaled to [-1, 1]
    assert tx["segments"][0]["words"][0]["word"] == "Hello"
    assert (tmp_path / "work" / "transcript.json").exists()


def test_load_wav_rejects_wrong_format(tmp_path):
    stereo = tmp_path / "stereo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", "-ac", "2", "-ar", "44100",
                    str(stereo)], check=True)
    with pytest.raises(ValueError):
        transcribe.load_wav(stereo)
