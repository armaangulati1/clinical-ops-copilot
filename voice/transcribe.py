"""Speech-to-text via the OpenAI Whisper API (``whisper-1``).

Honest-prototype boundaries:
  - This calls the hosted Whisper API and therefore needs ``OPENAI_API_KEY``.
  - We import the ``openai`` SDK lazily so importing this module never fails
    just because the optional dependency (or key) is absent. The demo entry
    script degrades to a ``--text`` override when transcription is unavailable,
    so the REST of the pipeline (the real agent + spoken reply) still runs.
"""

from __future__ import annotations

import os
from pathlib import Path


class TranscriptionUnavailable(RuntimeError):
    """Raised when Whisper transcription cannot run (missing key/SDK/file)."""


def whisper_available() -> bool:
    """True only if both the OpenAI SDK and an API key are present."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        import openai  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe_file(audio_path: Path, *, model: str = "whisper-1") -> str:
    """Transcribe an audio file with Whisper. Raises TranscriptionUnavailable.

    Supports whatever the Whisper API accepts (wav, m4a, mp3, ...).
    """
    if not audio_path.is_file():
        msg = f"Audio file not found: {audio_path}"
        raise TranscriptionUnavailable(msg)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        msg = (
            "OPENAI_API_KEY is not set. Whisper STT needs it. "
            "Re-run with --text \"<your question>\" to exercise the agent + "
            "spoken reply without live transcription."
        )
        raise TranscriptionUnavailable(msg)

    try:
        import openai
    except ImportError as exc:
        msg = (
            "The 'openai' package is not installed. Install it "
            "(uv pip install openai) or use --text to skip transcription."
        )
        raise TranscriptionUnavailable(msg) from exc

    client = openai.OpenAI(api_key=api_key)
    with audio_path.open("rb") as handle:
        result = client.audio.transcriptions.create(
            model=model,
            file=handle,
        )
    text = str(getattr(result, "text", "")).strip()
    if not text:
        msg = "Whisper returned an empty transcript."
        raise TranscriptionUnavailable(msg)
    return text
