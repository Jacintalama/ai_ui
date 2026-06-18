#!/usr/bin/env bash
# Pre-render the voice-picker preview clips. Run ON the render host (Piper +
# ffmpeg + the voice models live there). Produces /tmp/voicepreviews/<id>.mp3,
# which are then copied into mcp-servers/tasks/static/voices/ and committed.
#
# The sample line + voice ids MUST match mcp-servers/tasks/video_voices.py
# (SAMPLE_TEXT and the VOICES ids/model stems).
set -euo pipefail

TXT="Hey! This is how your video narration will sound with this voice."
OUT=/tmp/voicepreviews
mkdir -p "$OUT"
chmod 777 "$OUT"

# id -> model stem (under /opt/piper/voices/<stem>.onnx)
IDS=(amy ryan lessac joe alan alba)
STEMS=(en_US-amy-medium en_US-ryan-high en_US-lessac-medium en_US-joe-medium en_GB-alan-medium en_GB-alba-medium)

for i in "${!IDS[@]}"; do
  id="${IDS[$i]}"; stem="${STEMS[$i]}"
  echo "$TXT" | sudo -u claude-agent /opt/piper/piper \
    -m "/opt/piper/voices/$stem.onnx" -f "$OUT/$id.wav"
  ffmpeg -hide_banner -loglevel error -y -i "$OUT/$id.wav" -ac 1 -b:a 64k "$OUT/$id.mp3"
  echo "made $id.mp3 ($(du -h "$OUT/$id.mp3" | cut -f1))"
done

ls -la "$OUT"/*.mp3
