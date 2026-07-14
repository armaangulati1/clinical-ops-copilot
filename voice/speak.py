"""Text-to-speech via the macOS ``say`` command (zero extra dependencies).

We deliberately avoid heavy TTS packages for a prototype. ``say`` is built into
macOS. If it is unavailable (e.g. CI on Linux), ``speak`` no-ops after printing,
so the pipeline never crashes on a missing binary.
"""

from __future__ import annotations

import shutil
import subprocess

from schemas.decisions import Decision, DecisionAction

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
    """True if the macOS ``say`` binary is on PATH."""
    return shutil.which("say") is not None


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
    """Speak ``text`` aloud with ``say``. No-op (with notice) if unavailable."""
    if not say_available():
        print("[voice] macOS 'say' not found; skipping spoken output.")
        return
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    cmd.append(text)
    subprocess.run(cmd, check=False)
