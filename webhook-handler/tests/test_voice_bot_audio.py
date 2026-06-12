"""AudioOutputSource overflow behavior — the TTS mid-message cutout fix.

ElevenLabs streams TTS faster than realtime while Discord drains at exactly
50 fps, so the old 200-frame (4 s) queue overflowed on any reply longer than
~6 s and feed() silently dropped the tail: speech stopped mid-sentence.
"""
import sys

import pytest

# Other test modules stub sys.modules["discord"] / sys.modules["voice_bot"] so
# that `main` can be imported without audio deps. We need the real modules here
# — evict the stubs (modules already imported keep their stub references).
if "discord" in sys.modules and not hasattr(sys.modules["discord"], "AudioSource"):
    for _k in [k for k in sys.modules if k == "discord" or k.startswith("discord.")]:
        del sys.modules[_k]
pytest.importorskip("discord")
if "voice_bot" in sys.modules and not hasattr(sys.modules["voice_bot"], "ConversationalVoiceBot"):
    del sys.modules["voice_bot"]

import voice_bot as vb  # noqa: E402

DATA_FRAME = b"\x01" * vb.DISCORD_FRAME_SIZE


def _drain_data_frames(src) -> int:
    """Read until the queue is empty; count non-silence frames."""
    got = 0
    while True:
        frame = src.read()
        if frame == vb.SILENCE_FRAME:
            return got
        got += 1


def test_thirty_second_reply_plays_in_full():
    """1500 frames = 30 s of speech. The old 4 s queue dropped 1300 of them."""
    src = vb.AudioOutputSource()
    src.feed(DATA_FRAME * 1500)
    assert _drain_data_frames(src) == 1500
    assert src._dropped == 0


def test_queue_capacity_is_at_least_ninety_seconds():
    assert vb.OUTPUT_QUEUE_FRAMES >= 4500  # 90 s at 50 fps


def test_overflow_is_counted_and_logged(caplog):
    src = vb.AudioOutputSource()
    overflow = 10
    with caplog.at_level("WARNING"):
        src.feed(DATA_FRAME * (vb.OUTPUT_QUEUE_FRAMES + overflow))
    assert src._dropped == overflow
    assert any("output queue FULL" in r.message for r in caplog.records)


def test_pipeline_stats_expose_dropped():
    bot = vb.ConversationalVoiceBot(elevenlabs_api_key="k", agent_id="a")
    bot._audio_output = vb.AudioOutputSource()
    bot._audio_output._dropped = 7
    assert bot._pipeline_stats()["dropped"] == 7


# ---------------------------------------------------------------------------
# MicForwardLimiter — voice-recv flood containment (observed live 2026-06-12:
# ~12,500 sink writes/s vs the 50/s a real mic produces; the per-packet
# run_coroutine_threadsafe submissions saturated the event loop → delayed
# replies and drowned ASR).
# ---------------------------------------------------------------------------

def test_mic_limiter_allows_realtime_rate():
    t = [0.0]
    lim = vb.MicForwardLimiter(clock=lambda: t[0])
    allowed = 0
    for i in range(150):  # 3 s of real mic frames at 50/s
        t[0] = i * 0.02
        if lim.allow():
            allowed += 1
    assert allowed == 150
    assert lim.dropped == 0


def test_mic_limiter_blocks_flood():
    t = [0.0]
    lim = vb.MicForwardLimiter(clock=lambda: t[0])
    allowed = sum(1 for _ in range(10_000) if lim.allow())  # burst, same instant
    assert allowed == vb.MIC_FORWARD_MAX_PER_SEC
    assert lim.dropped == 10_000 - vb.MIC_FORWARD_MAX_PER_SEC


def test_mic_limiter_recovers_after_flood_window():
    t = [0.0]
    lim = vb.MicForwardLimiter(clock=lambda: t[0])
    for _ in range(500):
        lim.allow()
    t[0] = 1.1  # next window
    assert lim.allow() is True


def test_is_silence_detects_filler_frames():
    """Discord only transmits while the user speaks, so all-zero frames are
    library filler, never the mic — they must be droppable on sight."""
    assert vb.is_silence(b"\x00" * vb.DISCORD_FRAME_SIZE) is True
    assert vb.is_silence(b"") is True
    assert vb.is_silence(DATA_FRAME) is False
