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

# Run as a normal user rather than root (safer for a process that runs an AI agent).
RUN useradd --create-home worker && mkdir -p /data && chown -R worker /app /data
USER worker

ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
CMD ["python", "-m", "hub", "watch"]
