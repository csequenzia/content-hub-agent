FROM python:3.12-slim

# ffmpeg for cutting/encoding, libass via ffmpeg for captions, a bold font for captions
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the Whisper model at build time so the first video doesn't wait for it
ARG WHISPER_MODEL=base.en
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"

COPY . .

# Runs as root on purpose: Railway mounts volumes owned by root, and the Whisper
# model downloaded above lives in root's cache. Claude's tools are locked down in
# hub/agent.py (no shell, no web), so the agent itself can't use root access.
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
# Railway sets PORT; the upload page listens on it. Use "watch" instead for the folder watcher.
CMD ["python", "-m", "hub", "serve"]
