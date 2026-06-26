"""Curated voice library for the video generator narration.

Single source of truth for the selectable Piper voices. The UI picker (via the
``GET /api/video-jobs/voices`` endpoint), the upload allowlist validation, and
the host-side synthesis (model lookup in ``video_executor._voice``) all read
from here. A voice is resolved by id to a server-controlled model path; a user
value never becomes a path.

The voice ids and model filenames MUST match
``scripts/provision_piper_voices.sh`` (which downloads the ``.onnx`` models to
``/opt/piper/voices`` on the render host) and the preview clips under
``static/voices/<id>.mp3``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Directory where the Piper .onnx models live on the render host.
_VOICES_DIR = "/opt/piper/voices"


@dataclass(frozen=True)
class Voice:
    id: str
    label: str    # friendly name shown in the picker
    accent: str   # "US" | "UK"
    gender: str   # "Female" | "Male"
    model: str    # absolute .onnx path on the render host (server-controlled)


# Ordered curated library. The first entry is the default (Phase 1's voice).
VOICES: tuple[Voice, ...] = (
    Voice("amy", "Amy", "US", "Female", f"{_VOICES_DIR}/en_US-amy-medium.onnx"),
    Voice("ryan", "Ryan", "US", "Male", f"{_VOICES_DIR}/en_US-ryan-high.onnx"),
    Voice("lessac", "Lessac", "US", "Female", f"{_VOICES_DIR}/en_US-lessac-medium.onnx"),
    Voice("joe", "Joe", "US", "Male", f"{_VOICES_DIR}/en_US-joe-medium.onnx"),
    Voice("alan", "Alan", "UK", "Male", f"{_VOICES_DIR}/en_GB-alan-medium.onnx"),
    Voice("alba", "Alba", "UK", "Female", f"{_VOICES_DIR}/en_GB-alba-medium.onnx"),
)

_BY_ID: dict[str, Voice] = {v.id: v for v in VOICES}
DEFAULT_VOICE_ID = VOICES[0].id  # "amy"

# One shared sample line so users compare voices apples-to-apples. Used to
# pre-render the preview clips (see scripts/gen_voice_previews.sh).
SAMPLE_TEXT = "Hey! This is how your video narration will sound with this voice."


def is_valid_voice(voice_id: str | None) -> bool:
    """True only for an exact known voice id (used by the upload allowlist)."""
    return voice_id in _BY_ID


def resolve_model(voice_id: str | None) -> str:
    """Return the ``.onnx`` model path for ``voice_id``, default on miss.

    ``None`` (Phase 1 / pre-voice rows) and any unknown id resolve to the
    default voice so a render never fails on a missing or legacy voice.
    """
    return _BY_ID.get(voice_id or "", _BY_ID[DEFAULT_VOICE_ID]).model


def resolve_model_on_disk(voice_id: str | None, *, exists=os.path.exists) -> str | None:
    """Resolve ``voice_id`` to an *installed* ``.onnx`` model path.

    Prefers the requested voice, but falls back to the default voice's model
    when the requested one is not provisioned on the render host — so picking a
    voice whose model was never installed produces narration in the default
    voice instead of a silent video. Returns ``None`` only when no model exists
    at all (TTS then degrades to silent rather than crashing). ``exists`` is
    injectable for tests."""
    requested = _BY_ID.get(voice_id or "", _BY_ID[DEFAULT_VOICE_ID])
    if exists(requested.model):
        return requested.model
    default = _BY_ID[DEFAULT_VOICE_ID]
    if requested.id != default.id and exists(default.model):
        return default.model
    return None


def voice_catalog() -> list[dict]:
    """Picker payload for ``GET /api/video-jobs/voices`` (never exposes paths)."""
    return [
        {
            "id": v.id,
            "label": v.label,
            "accent": v.accent,
            "gender": v.gender,
            "default": v.id == DEFAULT_VOICE_ID,
            "sample_url": f"/tasks/static/voices/{v.id}.mp3",
        }
        for v in VOICES
    ]
