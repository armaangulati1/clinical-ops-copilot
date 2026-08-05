"""The spoken-decision leg: build the sentence, then say it out loud.

``spoken_answer`` phrases a :class:`Decision` and is used by every voice front
end, including the Twilio webhook. ``speak`` plays it locally.

Playback used to be hard-wired to the macOS ``say`` binary. It now goes through
the pluggable backend seam in :mod:`voice.tts`, selected by
``VOICE_TTS_BACKEND`` and **defaulting to ``say``**, so behaviour with no
configuration is byte-for-byte what it was.

The resilience contract is unchanged and deliberate: if the selected backend
cannot run (no ``say`` binary on Linux CI, no ElevenLabs key, no network, a
non-200, an exhausted quota), ``speak`` degrades to the fallback backend or
no-ops after printing a notice. It never raises, because a mute agent is a far
better failure than a crashed one.
"""

from __future__ import annotations

from schemas.decisions import Decision, DecisionAction
from voice.tts import say_binary_available, speak_text

_ACTION_PHRASING = {
    DecisionAction.SUBMIT: "Recommendation: submit the prior authorization.",
    DecisionAction.REQUEST_MORE_INFO: (
        "Recommendation: request more information before submitting."
    ),
    DecisionAction.DENY_RISK: (
        "Recommendation: flag this as a likely denial before filing."
    ),
}


def say_available() -> bool:
    """True if the macOS ``say`` binary is on PATH.

    Kept as the module's public name (callers and tests import it from here);
    the implementation now lives with the backends in :mod:`voice.tts`.
    """
    return say_binary_available()


def spoken_answer(case_id: str, decision: Decision) -> str:
    """Build a short, natural sentence describing the agent's decision."""
    action_line = _ACTION_PHRASING.get(
        decision.action,
        f"Recommendation: {decision.action.value}.",
    )
    confidence_pct = round(decision.confidence * 100)
    parts = [
        f"For {case_id}, the agent's decision is {decision.action.value}.",
        action_line,
        f"Confidence {confidence_pct} percent.",
    ]
    if decision.missing_fields:
        fields = ", ".join(f.replace("_", " ") for f in decision.missing_fields)
        parts.append(f"Missing fields: {fields}.")
    return " ".join(parts)


def speak(text: str, *, voice: str | None = None) -> None:
    """Speak ``text`` aloud with the selected backend.

    Defaults to macOS ``say``. Set ``VOICE_TTS_BACKEND=elevenlabs`` to use the
    ElevenLabs voice instead; any failure there falls back to ``say``. No-ops
    (with a printed notice) when nothing can speak. ``voice`` names a ``say``
    voice only; the ElevenLabs voice is chosen with ``ELEVENLABS_VOICE_ID``.
    """
    speak_text(text, voice=voice)
