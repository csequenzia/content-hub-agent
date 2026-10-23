# Node 22 for course lessons (HyperFrames). Copied in from the official image below.
FROM node:22-bookworm-slim AS node

# Debian trixie: its ffmpeg is 7.x, which the course scripts need (-/filter_complex)
FROM python:3.12-slim-trixie

# ffmpeg for cutting/encoding, libass via ffmpeg for captions, a bold font for captions,
# Chromium for rendering course lessons (HyperFrames draws each frame in a browser)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates chromium \
 && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# HyperFrames + GSAP for course lessons. Drop the Mac/Windows copies of its ONNX runtime (~130 MB).
COPY package.json package-lock.json ./
ENV PUPPETEER_SKIP_DOWNLOAD=1
RUN npm ci --omit=dev --no-audit --no-fund \
 && rm -rf node_modules/onnxruntime-node/bin/napi-v3/darwin node_modules/onnxruntime-node/bin/napi-v3/win32 \
 && npm cache clean --force

# Download the Whisper model at build time so the first video doesn't wait for it
ARG WHISPER_MODEL=base.en
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"

COPY . .

# Runs as root on purpose: Railway mounts volumes owned by root, and the Whisper
# model downloaded above lives in root's cache. Claude's tools are locked down in
# hub/agent.py (no shell, no web), so the agent itself can't use root access.
RUN mkdir -p /data

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data \
    HYPERFRAMES_BROWSER_PATH=/usr/bin/chromium DO_NOT_TRACK=1
# Railway sets PORT; the upload page listens on it. Use "watch" instead for the folder watcher.
CMD ["python", "-m", "hub", "serve"]
