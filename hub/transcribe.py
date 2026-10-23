"""Speech to text with word timestamps.

Uses faster-whisper (an optimized local Whisper) so no audio leaves the server and
there is no per-minute fee. Greg's desktop pipelines use openai-whisper with the same
"base.en" model; faster-whisper gives the same text and is lighter on a CPU-only
Railway box. Results are cached as work/<video>/transcript.json.
"""

import json
import wave
from pathlib import Path

import numpy as np

from . import config
from .media import extract_audio


def transcribe(video: Path, work: Path) -> dict:
    """Return {"duration": float, "segments": [{"start", "end", "text", "words": [...]}]}."""
    cache = work / "transcript.json"
    if cache.exists():
        return json.loads(cache.read_text())

    from faster_whisper import WhisperModel  # imported late: heavy, and tests don't need it

    audio = load_wav(extract_audio(video, work / "audio.wav"))
    model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type=config.WHISPER_COMPUTE_TYPE)
    segments, info = model.transcribe(audio, word_timestamps=True, vad_filter=True)
    out = {"duration": info.duration, "segments": []}
    for seg in segments:
        out["segments"].append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [
                {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                for w in (seg.words or [])
            ],
        })
    work.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=2))
    return out


def load_wav(path: Path) -> np.ndarray:
    """Read the 16 kHz mono WAV that ffmpeg made into the float array Whisper expects.

    We decode with ffmpeg ourselves instead of letting faster-whisper do it, because its
    decoder (PyAV) broke in av 19: open() no longer takes `metadata_errors`.
    """
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError(f"{path} is not 16 kHz mono 16-bit audio; delete it to re-extract")
        pcm = wav.readframes(wav.getnframes())
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def as_numbered_text(transcript: dict) -> str:
    """Compact view for Claude: one line per sentence with its time range."""
    lines = [f"Total length: {transcript['duration']:.1f}s"]
    for i, seg in enumerate(transcript["segments"]):
        lines.append(f"[{i}] {seg['start']:.2f}-{seg['end']:.2f}  {seg['text']}")
    return "\n".join(lines)
