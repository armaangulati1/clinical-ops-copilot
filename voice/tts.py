"""Pluggable text-to-speech backends for the spoken-decision leg.

The phone agent has always had exactly one voice: the macOS ``say`` binary for
local playback, and Twilio's own ``<Say>`` for the telephony leg. This module
adds a second backend (ElevenLabs) behind a seam so the two can be compared on
the same sentence, and so neither one is wired in as a hard dependency.

Selection is by environment variable:

    VOICE_TTS_BACKEND=say          # default; unchanged behaviour
    VOICE_TTS_BACKEND=elevenlabs   # HTTP synthesis, falls back to `say`

**Graceful degradation is the load-bearing property here**, and it is inherited
from the original ``voice/speak.py``: a missing binary made ``speak`` print a
notice and return rather than crash the pipeline. The same contract now covers
the network backend. No API key, no network, a non-200, a read timeout, or an
exhausted quota all fall back to ``say``; if ``say`` is unavailable too (Linux
CI), the call becomes a no-op with a printed notice. Nothing in this module
raises into the agent path.

Free-tier facts worth not rediscovering (verified against this account
2026-08-05, and they cost real API calls to learn):

* The API key in use is **restricted to ``text_to_speech`` + ``voices_read``**.
  Any call to ``/v1/user/*`` returns 401 by design; that is not a bug to fix.
* **Free accounts cannot use Voice Library voices over the API.** The request
  returns HTTP 402 ``"Free users cannot use library voices via the API"``. The
  widely-copied sample voice ``21m00Tcm4TlvDq8ikWAM`` (Rachel) is a library
  voice and therefore fails. Every voice this account can actually synthesize
  with is category ``premade``.
* ``EXAVITQu4vr4xnSDxMaL`` (Sarah) with ``eleven_turbo_v2_5`` is verified
  working, which is why it is the default here.

Demo scope: synthetic cases, one developer's free-tier account, local playback.
No production telephony path runs through this module (see ``README.md``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

# ---------------------------------------------------------------------------
# Environment contract
# ---------------------------------------------------------------------------

BACKEND_ENV = "VOICE_TTS_BACKEND"
SAY_BACKEND = "say"
ELEVENLABS_BACKEND = "elevenlabs"
DEFAULT_BACKEND = SAY_BACKEND

API_KEY_ENV = "ELEVENLABS_API_KEY"
VOICE_ID_ENV = "ELEVENLABS_VOICE_ID"
MODEL_ID_ENV = "ELEVENLABS_MODEL_ID"
OUTPUT_FORMAT_ENV = "ELEVENLABS_OUTPUT_FORMAT"
BASE_URL_ENV = "ELEVENLABS_BASE_URL"

# Sarah: a `premade` voice, verified synthesizable on this free-tier account.
# Do NOT swap in a Voice Library id (HTTP 402 on free tier; see module docstring).
DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_BASE_URL = "https://api.elevenlabs.io"
DEFAULT_TIMEOUT_SECONDS = 30.0

# Longest error body we echo. The body is ElevenLabs' own JSON error detail and
# never contains the request headers, but it is truncated anyway so a large or
# unexpected payload cannot flood a log line.
_MAX_ERROR_DETAIL = 300

# How often the `say` time-to-first-audio probe stats its output file. Any
# measurement taken this way carries up to one interval of quantization error,
# which is stated wherever the number is reported.
_FIRST_BYTE_POLL_SECONDS = 0.002

# Upper bound on any `say` invocation. A normal render of a one-sentence
# decision is ~3 s, so this is ~20x headroom; it exists to catch a wedged
# speechsynthesisd, not to police slow machines.
SAY_TIMEOUT_SECONDS = 60.0


class TTSError(RuntimeError):
    """A backend could not produce audio. Always caught before the agent path."""


@dataclass(frozen=True)
class SpeechAudio:
    """One synthesized utterance plus how long producing it took.

    ``latency_seconds`` is wall-clock time from the start of the synthesis call
    to holding the complete audio in memory. For ``say`` that is local
    render-to-file; for ElevenLabs it is the full HTTP round trip including
    network. Those are not the same kind of work, which is exactly the point of
    measuring both rather than assuming.
    """

    data: bytes
    backend: str
    media_type: str
    suffix: str
    latency_seconds: float

    def write(self, path: Path) -> Path:
        """Write the audio to ``path``, creating parent directories."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.data)
        return path


class TTSBackend(Protocol):
    """Minimal seam every backend implements."""

    name: str

    def is_available(self) -> bool:
        """True if this backend could plausibly run right now."""
        ...

    def synthesize(self, text: str) -> SpeechAudio:
        """Render ``text`` to audio bytes, or raise :class:`TTSError`."""
        ...

    def time_to_first_audio(self, text: str) -> float:
        """Seconds until this backend emits its first audio byte."""
        ...


# ---------------------------------------------------------------------------
# Backend: macOS `say` (the incumbent)
# ---------------------------------------------------------------------------


def say_binary_available() -> bool:
    """True if the macOS ``say`` binary is on PATH."""
    return shutil.which("say") is not None


class SayBackend:
    """macOS ``say``. Zero dependencies, zero network, zero cost.

    Every invocation is bounded by a timeout. ``say`` is a client of the system
    ``speechsynthesisd`` daemon rather than a self-contained renderer, and that
    daemon was observed wedging under rapid repeated invocation during the
    latency benchmark: a render that normally takes ~3 s sat blocked for over
    ten minutes with no CPU use. An unbounded ``subprocess`` call in a path whose
    whole promise is "never crash the pipeline" would just convert a crash into
    a hang, which is worse because nothing reports it.
    """

    name = SAY_BACKEND

    def __init__(
        self,
        *,
        voice: str | None = None,
        timeout_seconds: float = SAY_TIMEOUT_SECONDS,
    ) -> None:
        self.voice = voice
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return say_binary_available()

    def _command(self, extra: list[str]) -> list[str]:
        cmd = ["say"]
        if self.voice:
            cmd += ["-v", self.voice]
        return cmd + extra

    def synthesize(self, text: str) -> SpeechAudio:
        """Render to an AIFF file and read it back, timing the render only."""
        if not self.is_available():
            msg = "macOS 'say' binary not found on PATH"
            raise TTSError(msg)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "say.aiff"
            started = time.perf_counter()
            try:
                result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    self._command(["-o", str(out), text]),
                    capture_output=True,
                    check=False,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                msg = f"say did not finish within {self.timeout_seconds}s"
                raise TTSError(msg) from exc
            elapsed = time.perf_counter() - started
            if result.returncode != 0 or not out.exists():
                msg = f"say exited {result.returncode} without producing audio"
                raise TTSError(msg)
            data = out.read_bytes()
        return SpeechAudio(
            data=data,
            backend=self.name,
            media_type="audio/aiff",
            suffix=".aiff",
            latency_seconds=elapsed,
        )

    def time_to_first_audio(self, text: str) -> float:
        """Seconds until ``say`` has written its first audio bytes.

        Measured by polling the size of the output file while the render runs.
        This is a proxy for "synthesis has started emitting audio", not for when
        the speaker physically makes sound, and it carries up to one poll
        interval of quantization error. It is the closest apples-to-apples
        counterpart to a streaming API's time-to-first-byte that a
        render-to-file tool admits of.
        """
        if not self.is_available():
            msg = "macOS 'say' binary not found on PATH"
            raise TTSError(msg)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "say.aiff"
            started = time.perf_counter()
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                self._command(["-o", str(out), text]),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            first: float | None = None
            while True:
                if first is None and out.exists() and out.stat().st_size > 0:
                    first = time.perf_counter() - started
                if process.poll() is not None:
                    break
                if time.perf_counter() - started > self.timeout_seconds:
                    process.kill()
                    process.wait()
                    msg = f"say did not finish within {self.timeout_seconds}s"
                    raise TTSError(msg)
                time.sleep(_FIRST_BYTE_POLL_SECONDS)
            if first is None:
                # The render finished between polls, so first-byte is
                # unobservable; the total is a correct upper bound for it.
                if process.returncode != 0:
                    msg = f"say exited {process.returncode} without producing audio"
                    raise TTSError(msg)
                first = time.perf_counter() - started
        return first

    def speak(self, text: str) -> None:
        """Speak directly through the system audio device (no file round trip).

        Bounded like the render paths, and the timeout is swallowed rather than
        raised: ``speak`` is the end of the line, so a wedged synthesizer must
        cost the caller the sentence, not the process.
        """
        try:
            subprocess.run(  # noqa: S603 - fixed argv, no shell
                self._command([text]),
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            print(f"[voice] say did not finish within {self.timeout_seconds}s.")


# ---------------------------------------------------------------------------
# Backend: ElevenLabs
# ---------------------------------------------------------------------------


def _redact(message: str, secret: str | None) -> str:
    """Strip the API key from any message before it can reach a log."""
    if secret and secret in message:
        return message.replace(secret, "[REDACTED]")
    return message


class ElevenLabsBackend:
    """ElevenLabs ``/v1/text-to-speech/{voice_id}``, returning MP3 bytes.

    The key is read from the environment and never logged, printed, or written
    into a ``SpeechAudio``. Every failure mode is converted to :class:`TTSError`
    so the caller's fallback path is the only error handling the agent needs.
    """

    name = ELEVENLABS_BACKEND

    def __init__(
        self,
        *,
        api_key: str | None,
        voice_id: str = DEFAULT_VOICE_ID,
        model_id: str = DEFAULT_MODEL_ID,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    def is_available(self) -> bool:
        """A key must be present. Reachability is only knowable by trying."""
        return bool(self.api_key)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/v1/text-to-speech/{self.voice_id}"

    @property
    def stream_endpoint(self) -> str:
        """Chunked variant. Verified reachable under the same restricted key."""
        return f"{self.endpoint}/stream"

    def _headers(self) -> dict[str, str]:
        return {
            "xi-api-key": self.api_key or "",
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }

    def _payload(self, text: str) -> dict[str, str]:
        return {
            "text": text,
            "model_id": self.model_id,
            "output_format": self.output_format,
        }

    def synthesize(self, text: str) -> SpeechAudio:
        if not self.is_available():
            msg = f"{API_KEY_ENV} is not set"
            raise TTSError(msg)
        started = time.perf_counter()
        try:
            if self._client is not None:
                response = self._client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=self._payload(text),
                )
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self.endpoint,
                        headers=self._headers(),
                        json=self._payload(text),
                    )
        except httpx.HTTPError as exc:  # timeouts, DNS, connection resets
            msg = _redact(f"ElevenLabs request failed: {exc}", self.api_key)
            raise TTSError(msg) from exc
        elapsed = time.perf_counter() - started

        if response.status_code != 200:
            detail = _redact(response.text[:_MAX_ERROR_DETAIL], self.api_key)
            # 401 here means the key is missing/invalid for text_to_speech, NOT
            # the expected 401 from the restricted /v1/user/* endpoints.
            # 402 on a valid key almost always means a Voice Library voice on a
            # free account, or an exhausted character quota.
            msg = f"ElevenLabs returned HTTP {response.status_code}: {detail}"
            raise TTSError(msg)

        data = response.content
        if not data:
            msg = "ElevenLabs returned HTTP 200 with an empty body"
            raise TTSError(msg)

        return SpeechAudio(
            data=data,
            backend=self.name,
            media_type="audio/mpeg",
            suffix=".mp3",
            latency_seconds=elapsed,
        )

    def time_to_first_audio(self, text: str) -> float:
        """Seconds until the first non-empty chunk arrives from ``/stream``.

        Uses the chunked endpoint rather than the buffered one, because
        time-to-first-byte on a buffered response is just the total.
        """
        if not self.is_available():
            msg = f"{API_KEY_ENV} is not set"
            raise TTSError(msg)
        started = time.perf_counter()
        try:
            with (
                httpx.Client(timeout=self.timeout_seconds) as client,
                client.stream(
                    "POST",
                    self.stream_endpoint,
                    headers=self._headers(),
                    json=self._payload(text),
                ) as response,
            ):
                if response.status_code != 200:
                    response.read()
                    detail = _redact(
                        response.text[:_MAX_ERROR_DETAIL],
                        self.api_key,
                    )
                    msg = (
                        f"ElevenLabs stream returned HTTP "
                        f"{response.status_code}: {detail}"
                    )
                    raise TTSError(msg)
                for chunk in response.iter_bytes():
                    if chunk:
                        return time.perf_counter() - started
        except httpx.HTTPError as exc:
            msg = _redact(f"ElevenLabs stream failed: {exc}", self.api_key)
            raise TTSError(msg) from exc
        msg = "ElevenLabs stream produced no audio chunks"
        raise TTSError(msg)

    def speak(self, text: str) -> None:
        """Synthesize then play locally. Raises ``TTSError`` on any failure."""
        audio = self.synthesize(text)
        play_audio(audio)


# ---------------------------------------------------------------------------
# Local playback
# ---------------------------------------------------------------------------


def player_available() -> bool:
    """True if the macOS ``afplay`` binary is on PATH."""
    return shutil.which("afplay") is not None


def play_audio(audio: SpeechAudio) -> bool:
    """Play synthesized audio via ``afplay``. Returns False if it could not.

    Never raises: a machine without ``afplay`` is a machine that hears nothing,
    not a machine whose pipeline dies.
    """
    if not player_available():
        print("[voice] 'afplay' not found; skipping playback.")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"utterance{audio.suffix}"
        path.write_bytes(audio.data)
        try:
            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["afplay", str(path)],
                check=False,
                timeout=SAY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print("[voice] afplay did not finish in time; skipping playback.")
            return False
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Selection + fallback
# ---------------------------------------------------------------------------


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def selected_backend_name(environ: Mapping[str, str] | None = None) -> str:
    """The backend named by ``VOICE_TTS_BACKEND``, defaulting to ``say``.

    An unrecognized value falls back to the default rather than raising, so a
    typo in a deploy env degrades to the incumbent voice instead of muting the
    agent.
    """
    env = _env(environ)
    raw = env.get(BACKEND_ENV, "").strip().lower()
    if raw in (SAY_BACKEND, ELEVENLABS_BACKEND):
        return raw
    if raw:
        print(f"[voice] unknown {BACKEND_ENV}={raw!r}; using {DEFAULT_BACKEND}.")
    return DEFAULT_BACKEND


def build_elevenlabs_backend(
    environ: Mapping[str, str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> ElevenLabsBackend:
    """Construct the ElevenLabs backend from the environment."""
    env = _env(environ)
    return ElevenLabsBackend(
        api_key=env.get(API_KEY_ENV) or None,
        voice_id=env.get(VOICE_ID_ENV) or DEFAULT_VOICE_ID,
        model_id=env.get(MODEL_ID_ENV) or DEFAULT_MODEL_ID,
        output_format=env.get(OUTPUT_FORMAT_ENV) or DEFAULT_OUTPUT_FORMAT,
        base_url=env.get(BASE_URL_ENV) or DEFAULT_BASE_URL,
        client=client,
    )


def build_backend(
    name: str,
    environ: Mapping[str, str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> TTSBackend:
    """Construct a backend by name."""
    if name == ELEVENLABS_BACKEND:
        return build_elevenlabs_backend(environ, client=client)
    return SayBackend()


def resolve_backend(
    environ: Mapping[str, str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> TTSBackend:
    """The backend the environment currently selects."""
    return build_backend(selected_backend_name(environ), environ, client=client)


@dataclass(frozen=True)
class SynthesisOutcome:
    """What actually happened, including whether the fallback fired.

    ``audio`` is None only when every backend failed, which on a Mac with
    ``say`` present should not happen.
    """

    audio: SpeechAudio | None
    requested_backend: str
    used_backend: str | None
    fell_back: bool
    error: str | None = None


def synthesize(
    text: str,
    environ: Mapping[str, str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> SynthesisOutcome:
    """Synthesize ``text`` with the selected backend, falling back to ``say``.

    Never raises. This is the function the agent path calls, and its contract is
    that a broken TTS backend costs you the nicer voice, not the decision.
    """
    requested = selected_backend_name(environ)
    primary = build_backend(requested, environ, client=client)
    try:
        return SynthesisOutcome(
            audio=primary.synthesize(text),
            requested_backend=requested,
            used_backend=primary.name,
            fell_back=False,
        )
    except TTSError as exc:
        first_error = str(exc)
    except Exception as exc:  # a backend must never surprise the agent path
        first_error = f"unexpected {type(exc).__name__}: {exc}"

    if requested == DEFAULT_BACKEND:
        print(f"[voice] {requested} synthesis failed: {first_error}")
        return SynthesisOutcome(
            audio=None,
            requested_backend=requested,
            used_backend=None,
            fell_back=False,
            error=first_error,
        )

    print(f"[voice] {requested} failed ({first_error}); falling back to say.")
    fallback = SayBackend()
    try:
        return SynthesisOutcome(
            audio=fallback.synthesize(text),
            requested_backend=requested,
            used_backend=fallback.name,
            fell_back=True,
            error=first_error,
        )
    except TTSError as exc:
        combined = f"{first_error}; fallback also failed: {exc}"
        print(f"[voice] no TTS backend available: {combined}")
        return SynthesisOutcome(
            audio=None,
            requested_backend=requested,
            used_backend=None,
            fell_back=True,
            error=combined,
        )


def speak_text(
    text: str,
    environ: Mapping[str, str] | None = None,
    *,
    voice: str | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """Speak ``text`` aloud with the selected backend. Returns the backend used.

    Returns None when nothing could speak (no ``say`` on a Linux box, no key and
    no fallback). The original no-op-with-a-notice behaviour is preserved
    exactly for the default ``say`` path, which still shells straight out to the
    binary rather than rendering a file first.
    """
    requested = selected_backend_name(environ)

    if requested == SAY_BACKEND:
        backend = SayBackend(voice=voice)
        if not backend.is_available():
            print("[voice] macOS 'say' not found; skipping spoken output.")
            return None
        backend.speak(text)
        return backend.name

    outcome = synthesize(text, environ, client=client)
    if outcome.audio is None:
        return None
    if outcome.used_backend == SAY_BACKEND:
        # The fallback path: speak through `say` directly rather than replaying
        # the rendered AIFF, so it sounds identical to the incumbent behaviour.
        SayBackend(voice=voice).speak(text)
        return SAY_BACKEND
    if not play_audio(outcome.audio):
        return None
    return outcome.used_backend
