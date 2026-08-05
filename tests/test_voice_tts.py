"""Tests for the pluggable TTS backend seam.

**No test here touches the network by default.** The ElevenLabs HTTP layer is
mocked with an ``httpx.MockTransport``, so the request the backend would really
send (URL, headers, JSON body) is asserted byte-for-byte without a call being
made. The single live test is marked ``network`` and is therefore excluded from
the CI gate (``-m "not network and not ocr and not browser"``); it costs real
API credits and needs a real key, so it must be opted into.

The property under test that matters most is **graceful degradation**: a
missing key, a refused connection, a 401, a 402 (free-tier library voice or an
exhausted quota), a timeout, and an empty 200 must each fall back to ``say`` and
never raise into the agent path. That contract predates ElevenLabs (the original
``speak`` no-opped rather than crashing on a missing binary) and the new backend
inherits it rather than weakening it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import httpx
import pytest

from voice import tts
from voice.speak import speak
from voice.tts import (
    DEFAULT_MODEL_ID,
    DEFAULT_VOICE_ID,
    ELEVENLABS_BACKEND,
    SAY_BACKEND,
    ElevenLabsBackend,
    SayBackend,
    SpeechAudio,
    TTSError,
    build_backend,
    resolve_backend,
    selected_backend_name,
    synthesize,
)

FAKE_KEY = "sk_" + "0" * 48
MP3_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00fake-mp3-payload"
SENTENCE = "For case-003, the agent's decision is request-more-info."


def eleven_env(**overrides: str) -> dict[str, str]:
    env = {"VOICE_TTS_BACKEND": ELEVENLABS_BACKEND, "ELEVENLABS_API_KEY": FAKE_KEY}
    env.update(overrides)
    return env


def mock_client(handler: object) -> httpx.Client:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return httpx.Client(transport=transport)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_default_backend_is_say_when_env_is_empty() -> None:
    """No configuration must mean exactly the old behaviour."""
    assert selected_backend_name({}) == SAY_BACKEND
    assert isinstance(resolve_backend({}), SayBackend)


def test_env_var_selects_elevenlabs() -> None:
    assert selected_backend_name(eleven_env()) == ELEVENLABS_BACKEND
    assert isinstance(resolve_backend(eleven_env()), ElevenLabsBackend)


@pytest.mark.parametrize("raw", ["ELEVENLABS", "  elevenlabs  ", "ElevenLabs"])
def test_backend_name_is_case_and_whitespace_insensitive(raw: str) -> None:
    assert selected_backend_name({"VOICE_TTS_BACKEND": raw}) == ELEVENLABS_BACKEND


def test_unknown_backend_name_degrades_to_say_rather_than_raising() -> None:
    """A typo in a deploy env must mute nothing."""
    assert selected_backend_name({"VOICE_TTS_BACKEND": "eleven-labs"}) == SAY_BACKEND


def test_elevenlabs_config_comes_from_the_environment() -> None:
    backend = build_backend(
        ELEVENLABS_BACKEND,
        eleven_env(
            ELEVENLABS_VOICE_ID="voice-xyz",
            ELEVENLABS_MODEL_ID="model-abc",
            ELEVENLABS_BASE_URL="https://example.test/",
        ),
    )
    assert isinstance(backend, ElevenLabsBackend)
    assert backend.voice_id == "voice-xyz"
    assert backend.model_id == "model-abc"
    # Trailing slash stripped so the endpoint never contains a double slash.
    assert backend.endpoint == "https://example.test/v1/text-to-speech/voice-xyz"
    assert backend.stream_endpoint.endswith("/stream")


def test_defaults_are_the_free_tier_verified_voice_and_model() -> None:
    """Guards the expensive-to-rediscover fact.

    ``21m00Tcm4TlvDq8ikWAM`` (Rachel) is a Voice **Library** voice, and a free
    account calling it gets HTTP 402 "Free users cannot use library voices via
    the API". The default must stay a `premade` voice.
    """
    backend = build_backend(ELEVENLABS_BACKEND, eleven_env())
    assert isinstance(backend, ElevenLabsBackend)
    assert backend.voice_id == DEFAULT_VOICE_ID == "EXAVITQu4vr4xnSDxMaL"
    assert backend.model_id == DEFAULT_MODEL_ID == "eleven_turbo_v2_5"
    assert backend.voice_id != "21m00Tcm4TlvDq8ikWAM"


# ---------------------------------------------------------------------------
# The request actually sent
# ---------------------------------------------------------------------------


def test_successful_synthesis_sends_the_documented_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["api_key"] = request.headers.get("xi-api-key")
        seen["accept"] = request.headers.get("accept")
        seen["body"] = request.read().decode()
        return httpx.Response(200, content=MP3_BYTES)

    backend = ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler))
    audio = backend.synthesize(SENTENCE)

    assert seen["method"] == "POST"
    assert seen["url"] == (
        f"https://api.elevenlabs.io/v1/text-to-speech/{DEFAULT_VOICE_ID}"
    )
    assert seen["api_key"] == FAKE_KEY
    assert seen["accept"] == "audio/mpeg"
    body = str(seen["body"])
    assert SENTENCE in body
    assert DEFAULT_MODEL_ID in body

    assert audio.data == MP3_BYTES
    assert audio.backend == ELEVENLABS_BACKEND
    assert audio.media_type == "audio/mpeg"
    assert audio.suffix == ".mp3"
    assert audio.latency_seconds >= 0


def test_synthesis_never_calls_a_restricted_user_endpoint() -> None:
    """The key is scoped to text_to_speech + voices_read.

    Any request to ``/v1/user/*`` returns 401 by design, so the backend must
    never make one (a subscription "check" would break the whole path).
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=MP3_BYTES)

    ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler)).synthesize("hi")
    assert calls == [f"/v1/text-to-speech/{DEFAULT_VOICE_ID}"]
    assert not any(path.startswith("/v1/user") for path in calls)


def test_audio_can_be_written_to_disk(tmp_path: Path) -> None:
    audio = SpeechAudio(
        data=MP3_BYTES,
        backend=ELEVENLABS_BACKEND,
        media_type="audio/mpeg",
        suffix=".mp3",
        latency_seconds=0.5,
    )
    written = audio.write(tmp_path / "nested" / "decision.mp3")
    assert written.read_bytes() == MP3_BYTES


# ---------------------------------------------------------------------------
# Failure modes -> TTSError
# ---------------------------------------------------------------------------


def test_missing_key_is_unavailable_and_raises_rather_than_calling() -> None:
    backend = ElevenLabsBackend(api_key=None)
    assert backend.is_available() is False
    with pytest.raises(TTSError, match="ELEVENLABS_API_KEY"):
        backend.synthesize(SENTENCE)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, '{"detail":"invalid api key"}'),
        (402, '{"detail":"Free users cannot use library voices via the API"}'),
        (422, '{"detail":"voice_id not found"}'),
        (429, '{"detail":"too many requests"}'),
        (500, "upstream error"),
    ],
)
def test_non_200_becomes_a_tts_error(status: int, body: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    backend = ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler))
    with pytest.raises(TTSError, match=f"HTTP {status}"):
        backend.synthesize(SENTENCE)


def test_empty_200_body_becomes_a_tts_error() -> None:
    """A 200 with no audio is a failure, not a silent success."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    backend = ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler))
    with pytest.raises(TTSError, match="empty body"):
        backend.synthesize(SENTENCE)


def test_transport_failure_becomes_a_tts_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    backend = ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler))
    with pytest.raises(TTSError, match="request failed"):
        backend.synthesize(SENTENCE)


def test_timeout_becomes_a_tts_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    backend = ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler))
    with pytest.raises(TTSError, match="request failed"):
        backend.synthesize(SENTENCE)


def test_error_messages_never_leak_the_api_key() -> None:
    """An error body that echoes the key back must be redacted before printing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f'{{"detail":"bad key {FAKE_KEY}"}}')

    backend = ElevenLabsBackend(api_key=FAKE_KEY, client=mock_client(handler))
    with pytest.raises(TTSError) as excinfo:
        backend.synthesize(SENTENCE)
    assert FAKE_KEY not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)


def test_redaction_control_can_detect_a_leak() -> None:
    """Control: the assertion above can fail, so a pass is real evidence."""
    assert tts._redact(f"key={FAKE_KEY}", FAKE_KEY) == "key=[REDACTED]"
    assert tts._redact(f"key={FAKE_KEY}", None) == f"key={FAKE_KEY}"


# ---------------------------------------------------------------------------
# Graceful degradation: the contract the agent path depends on
# ---------------------------------------------------------------------------


class _FailingBackend:
    """A backend that always fails, standing in for a dead network or quota."""

    name = ELEVENLABS_BACKEND

    def __init__(self, error: Exception) -> None:
        self.error = error

    def is_available(self) -> bool:
        return True

    def synthesize(self, text: str) -> SpeechAudio:
        raise self.error

    def time_to_first_audio(self, text: str) -> float:
        raise self.error


def _stub_say(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace SayBackend with a recorder so no audio is rendered in tests."""
    spoken: list[str] = []

    def fake_synthesize(self: SayBackend, text: str) -> SpeechAudio:
        spoken.append(text)
        return SpeechAudio(
            data=b"FORM....AIFF",
            backend=SAY_BACKEND,
            media_type="audio/aiff",
            suffix=".aiff",
            latency_seconds=0.01,
        )

    monkeypatch.setattr(SayBackend, "synthesize", fake_synthesize)
    monkeypatch.setattr(SayBackend, "is_available", lambda self: True)
    return spoken


@pytest.mark.parametrize(
    "error",
    [
        TTSError("ElevenLabs returned HTTP 402: quota exhausted"),
        TTSError("ElevenLabs request failed: connection refused"),
        RuntimeError("something nobody predicted"),
    ],
)
def test_elevenlabs_failure_falls_back_to_say(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key, no network, non-200, or quota exhausted must never crash."""
    spoken = _stub_say(monkeypatch)
    monkeypatch.setattr(
        tts,
        "build_backend",
        lambda name, environ=None, client=None: _FailingBackend(error),
    )

    outcome = synthesize(SENTENCE, eleven_env())

    assert outcome.audio is not None
    assert outcome.requested_backend == ELEVENLABS_BACKEND
    assert outcome.used_backend == SAY_BACKEND
    assert outcome.fell_back is True
    assert outcome.error is not None
    assert spoken == [SENTENCE]


def test_missing_key_falls_back_to_say(monkeypatch: pytest.MonkeyPatch) -> None:
    """The commonest real case: ELEVENLABS_BACKEND selected with no key set."""
    spoken = _stub_say(monkeypatch)
    outcome = synthesize(SENTENCE, {"VOICE_TTS_BACKEND": ELEVENLABS_BACKEND})
    assert outcome.used_backend == SAY_BACKEND
    assert outcome.fell_back is True
    assert spoken == [SENTENCE]


def test_no_backend_at_all_returns_none_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux CI with no `say` and no key: the pipeline must still not die."""
    monkeypatch.setattr(SayBackend, "is_available", lambda self: False)
    outcome = synthesize(SENTENCE, {"VOICE_TTS_BACKEND": ELEVENLABS_BACKEND})
    assert outcome.audio is None
    assert outcome.used_backend is None
    assert outcome.error is not None


def test_say_failure_does_not_pretend_to_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `say` IS the request, there is nowhere to fall back to."""
    monkeypatch.setattr(SayBackend, "is_available", lambda self: False)
    outcome = synthesize(SENTENCE, {})
    assert outcome.audio is None
    assert outcome.requested_backend == SAY_BACKEND
    assert outcome.fell_back is False


def test_successful_elevenlabs_synthesis_does_not_fall_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=MP3_BYTES)

    outcome = synthesize(SENTENCE, eleven_env(), client=mock_client(handler))
    assert outcome.used_backend == ELEVENLABS_BACKEND
    assert outcome.fell_back is False
    assert outcome.audio is not None
    assert outcome.audio.data == MP3_BYTES


# ---------------------------------------------------------------------------
# voice.speak still behaves exactly as before by default
# ---------------------------------------------------------------------------


def test_speak_defaults_to_say_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOICE_TTS_BACKEND", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(SayBackend, "is_available", lambda self: True)
    monkeypatch.setattr(
        SayBackend,
        "speak",
        lambda self, text: calls.append(text),
    )
    speak(SENTENCE)
    assert calls == [SENTENCE]


def test_speak_no_ops_when_say_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The original resilience property: a missing binary is not a crash."""
    monkeypatch.delenv("VOICE_TTS_BACKEND", raising=False)
    monkeypatch.setattr(SayBackend, "is_available", lambda self: False)
    called: list[str] = []
    monkeypatch.setattr(SayBackend, "speak", lambda self, text: called.append(text))
    speak(SENTENCE)  # must not raise
    assert called == [], "a missing binary must not be spoken through"


def test_speak_text_reports_which_backend_spoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SayBackend, "is_available", lambda self: True)
    monkeypatch.setattr(SayBackend, "speak", lambda self, text: None)
    assert tts.speak_text(SENTENCE, {}) == SAY_BACKEND


# ---------------------------------------------------------------------------
# A wedged `say` must time out, not hang forever
# ---------------------------------------------------------------------------


def test_say_render_timeout_becomes_a_tts_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`say` is a client of speechsynthesisd, and that daemon can wedge.

    Observed during the latency benchmark: a render that normally takes ~3 s sat
    blocked for over ten minutes with no CPU use. An unbounded subprocess call
    would turn "never crash the pipeline" into "hang the pipeline", which is
    worse because nothing reports it.
    """

    def fake_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="say", timeout=60.0)

    monkeypatch.setattr(SayBackend, "is_available", lambda self: True)
    monkeypatch.setattr("voice.tts.subprocess.run", fake_run)
    with pytest.raises(TTSError, match="did not finish within"):
        SayBackend().synthesize(SENTENCE)


def test_wedged_say_does_not_hang_the_fallback_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both backends down (one failing, one wedged) still returns cleanly."""

    def fake_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="say", timeout=60.0)

    monkeypatch.setattr(SayBackend, "is_available", lambda self: True)
    monkeypatch.setattr("voice.tts.subprocess.run", fake_run)
    outcome = synthesize(SENTENCE, {"VOICE_TTS_BACKEND": ELEVENLABS_BACKEND})
    assert outcome.audio is None
    assert outcome.error is not None
    assert "did not finish within" in outcome.error


def test_say_speak_swallows_a_timeout_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`speak` is the end of the line: a wedge costs the sentence, not the process."""

    def fake_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="say", timeout=60.0)

    monkeypatch.setattr("voice.tts.subprocess.run", fake_run)
    SayBackend().speak(SENTENCE)  # must not raise


def test_every_say_invocation_passes_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: proves the timeout is actually plumbed through, not just defined."""
    seen: list[object] = []

    class _Completed:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(*args: object, **kwargs: object) -> object:
        seen.append(kwargs.get("timeout"))
        return _Completed()

    monkeypatch.setattr("voice.tts.subprocess.run", fake_run)
    SayBackend(timeout_seconds=12.5).speak(SENTENCE)
    assert seen == [12.5]


def test_play_audio_no_ops_without_a_player(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts, "player_available", lambda: False)
    audio = SpeechAudio(
        data=MP3_BYTES,
        backend=ELEVENLABS_BACKEND,
        media_type="audio/mpeg",
        suffix=".mp3",
        latency_seconds=0.1,
    )
    assert tts.play_audio(audio) is False


# ---------------------------------------------------------------------------
# Live, opt-in only
# ---------------------------------------------------------------------------


@pytest.mark.network
def test_live_elevenlabs_synthesis_returns_mp3() -> None:
    """Opt-in: costs real credits and needs a real key.

        uv run pytest tests/test_voice_tts.py -m network

    Excluded from the CI gate, which runs ``-m "not network ..."``.
    """
    if not os.environ.get("ELEVENLABS_API_KEY"):
        pytest.skip("ELEVENLABS_API_KEY not set")
    backend = build_backend(ELEVENLABS_BACKEND, os.environ)
    audio = backend.synthesize("Confidence 70 percent.")
    assert audio.data[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")
    assert len(audio.data) > 1000
    assert audio.latency_seconds > 0
