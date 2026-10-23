"""An agent's answer, said out loud (2026-10-23, "how the ai agent talk to
user ... have mic enable and disable").

The office chat gets a voice in two halves. Hearing is the browser's own
speech recognition, which never reaches this service: the words arrive as
an ordinary message on /tasks/agents/chat/send. Speaking is here: the
client sends one sentence of an answer at a time to /agents/voice/say and
gets a WAV back, made by Piper, the offline text-to-speech already baked
into this container for video narration (Dockerfile, video_voices.py). No
account, no key, no network.

What is spoken is a cleaned reading of the answer: code, links and markdown
marks are not read character by character. The text is capped, one voice
job runs per request with a hard timeout, at most a couple at once (the
server has 3.8 GB), and a person gets a fixed number of sentences a minute.
Everything fails soft on the client: a 503 from here is an answer that
stays text.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from collections import defaultdict, deque

import video_voices

log = logging.getLogger("agent_voice")

PIPER_BIN = os.environ.get("PIPER_BIN", "/opt/piper/piper")
#: The most that is read from one request. A sentence of an answer, not
#: the answer; the client splits.
MAX_CHARS = 600
#: Piper on this CPU does a sentence in well under a second; a job that
#: takes this long is stuck.
TIMEOUT_S = 25
#: How many sentences one person may ask for in a minute. A meeting of
#: three agents answering at length is about 30.
RATE_PER_MINUTE = 60
#: Voice jobs at once, whoever asks. Two Piper processes are ~200 MB.
CONCURRENT = 2


class VoiceError(Exception):
    """The voice could not be made. The reason is for the log; the client
    falls back to text whatever it was."""


# --- the words ---------------------------------------------------------------

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_TAG = re.compile(r"<[^>\n]{1,80}>")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
_QUOTE = re.compile(r"^\s*>\s?", re.M)
_TABLE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.M)
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)
_EMPH = re.compile(r"(\*\*|__|\*|_|~~)")
_PIPE = re.compile(r"\s*\|\s*")
_SPACE = re.compile(r"\s+")


def spoken_text(raw: str) -> str:
    """The reading of a markdown answer: what a person would say aloud.

    Code is "code", a link is its text, a bare address is "a link", and
    the marks that shape the page (#, *, >, |) are dropped. Whitespace is
    folded. The result is capped at MAX_CHARS, at a sentence end where one
    falls in the last third."""
    s = raw or ""
    s = _FENCE.sub(" code. ", s)
    s = _INLINE_CODE.sub(" code ", s)
    s = _IMAGE.sub(" ", s)
    s = _LINK.sub(r"\1", s)
    s = _URL.sub(" a link ", s)
    s = _TAG.sub(" ", s)
    s = _TABLE.sub(" ", s)
    s = _RULE.sub(" ", s)
    s = _HEADING.sub("", s)
    s = _BULLET.sub("", s)
    s = _QUOTE.sub("", s)
    s = _EMPH.sub("", s)
    s = _PIPE.sub(", ", s)
    s = _SPACE.sub(" ", s).strip()
    if len(s) > MAX_CHARS:
        cut = s[:MAX_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        s = cut[:end + 1] if end > MAX_CHARS * 2 // 3 else cut.rstrip() + "."
    return s


def voice_or_default(voice_id: str | None) -> str:
    """A known voice id, else the default. Never a path, never user text."""
    return voice_id if video_voices.is_valid_voice(voice_id) else video_voices.DEFAULT_VOICE_ID


# --- the rate ----------------------------------------------------------------

class RateLimit:
    """Sentences per person per minute, in memory. One process serves the
    office, so this is the whole picture; restarting forgets, which is
    fine for a limit that exists to stop a loop, not to bill."""

    def __init__(self, per_minute: int = RATE_PER_MINUTE):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, who: str, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        q = self._hits[who]
        while q and t - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(t)
        return True


LIMIT = RateLimit()
_SLOTS: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    # Made on first use, inside the running loop.
    global _SLOTS
    if _SLOTS is None:
        _SLOTS = asyncio.Semaphore(CONCURRENT)
    return _SLOTS


# --- the sound ---------------------------------------------------------------

async def _run_piper(model: str, text: str) -> bytes:
    """Piper reads the sentence on stdin and writes a WAV; the file is read
    back and removed. No user text crosses a shell: every argument is a
    fixed path, and the words go through the pipe."""
    with tempfile.TemporaryDirectory(prefix="aiui-voice-") as tmp:
        wav = os.path.join(tmp, "say.wav")
        proc = await asyncio.create_subprocess_exec(
            PIPER_BIN, "-m", model, "-f", wav,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(text.encode("utf-8")), TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            raise VoiceError("piper took longer than %ss" % TIMEOUT_S)
        if proc.returncode != 0:
            raise VoiceError("piper exit %s: %s" % (proc.returncode, (err or b"")[:200].decode("utf-8", "replace")))
        try:
            with open(wav, "rb") as f:
                data = f.read()
        except OSError as exc:
            raise VoiceError("piper wrote no file: %s" % exc)
    if len(data) < 64:
        raise VoiceError("piper wrote an empty file")
    return data


#: Seam. Tests monkeypatch this rather than running a synthesiser.
_run = _run_piper


async def synthesize(text: str, voice_id: str | None, *, exists=os.path.exists) -> bytes:
    """WAV bytes of `text` in `voice_id`, or VoiceError.

    The voice is resolved to an installed model (default on a miss, as the
    video narration does); no model at all, or no Piper binary, is a
    VoiceError before anything is spawned."""
    words = spoken_text(text)
    if not words:
        raise VoiceError("nothing to say")
    model = video_voices.resolve_model_on_disk(voice_or_default(voice_id), exists=exists)
    if not model:
        raise VoiceError("no voice model installed")
    if not exists(PIPER_BIN):
        raise VoiceError("piper is not installed at %s" % PIPER_BIN)
    async with _slots():
        return await _run(model, words)
