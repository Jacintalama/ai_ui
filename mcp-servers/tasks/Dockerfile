FROM python:3.11-slim

# Install Node.js (for @anthropic-ai/claude-code) and git
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git openssh-client rsync ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium for server-side site capture (video URL auto-capture). Installed at
# build time so runtime only pays a transient, serialized memory spike.
RUN python -m playwright install --with-deps chromium
# Piper TTS for in-container animated-video narration. Best-effort: a download
# blip must NOT break the build, and render_animated_job falls back to silent
# video if /opt/piper/piper or the voice model is missing.
RUN mkdir -p /opt/piper/voices && \
    ( curl -fsSL https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_amd64.tar.gz -o /tmp/piper.tgz \
      && tar -xzf /tmp/piper.tgz -C /opt && rm -f /tmp/piper.tgz \
      && curl -fsSL "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" -o /opt/piper/voices/en_US-amy-medium.onnx \
      && curl -fsSL "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json" -o /opt/piper/voices/en_US-amy-medium.onnx.json \
      && echo "piper installed" ) \
    || echo "piper install skipped (animated narration disabled)"
COPY . .
EXPOSE 8210
# Use standard asyncio event loop — uvloop has issues with async subprocess
# pipes which breaks the claude CLI integration.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8210", "--loop", "asyncio"]
