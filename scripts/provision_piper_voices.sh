#!/usr/bin/env bash
# Provision the curated Piper voice library for the AIUI video generator.
#
# Run this ON the render host (where /opt/piper/piper lives), e.g.:
#   scp scripts/provision_piper_voices.sh root@HOST:/tmp/ && ssh root@HOST bash /tmp/provision_piper_voices.sh
#
# Idempotent: voices already present are skipped. Models come from
# rhasspy/piper-voices (MIT-licensed at runtime). The voice ids here MUST match
# the allowlist in mcp-servers/tasks/video_voices.py.
set -euo pipefail

BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"
DEST="/opt/piper/voices"

# voice_id | repo_relative_dir | file_stem
VOICES=(
  "amy|en/en_US/amy/medium|en_US-amy-medium"
  "ryan|en/en_US/ryan/high|en_US-ryan-high"
  "lessac|en/en_US/lessac/medium|en_US-lessac-medium"
  "joe|en/en_US/joe/medium|en_US-joe-medium"
  "alan|en/en_GB/alan/medium|en_GB-alan-medium"
  "alba|en/en_GB/alba/medium|en_GB-alba-medium"
)

mkdir -p "$DEST"
for entry in "${VOICES[@]}"; do
  IFS='|' read -r vid rel stem <<< "$entry"
  for ext in onnx onnx.json; do
    out="$DEST/$stem.$ext"
    if [ -s "$out" ]; then
      echo "skip   $stem.$ext (already present)"
      continue
    fi
    echo "fetch  $stem.$ext"
    curl -fsSL "$BASE/$rel/$stem.$ext" -o "$out.tmp"
    mv "$out.tmp" "$out"
  done
done

# Piper runs as claude-agent; make sure it can read the models.
chown -R claude-agent:claude-agent "$DEST" 2>/dev/null || true

echo "--- installed voice models ---"
ls -lh "$DEST"/*.onnx
