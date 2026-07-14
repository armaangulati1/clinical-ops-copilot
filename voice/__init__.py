"""Shared voice glue for clinical-ops-copilot.

This package holds the small, deterministic pieces that sit around the
EXISTING prior-auth agent when it is driven by voice. It does NOT modify the
agent, MCP wiring, or any production code. Two building blocks live here and
are reused by every voice front-end:

  1. ``voice.route.case_id_from_transcript``: resolve a spoken question to an
     existing ``case-0NN`` id (deterministic, no extra LLM call),
  2. ``voice.speak.spoken_answer``: phrase the agent's decision as one short,
     natural sentence for a text-to-speech reply.

The original file-in / spoken-out prototype (Whisper -> agent -> macOS ``say``)
lives on the ``voice-prototype`` branch. The real-telephony front-end
(``voice_telephony/``) reuses the same two building blocks so the agent path is
identical no matter how the question arrives. In every case the voice layer
only routes and phrases; the REAL agent makes 100% of the decision.
"""
