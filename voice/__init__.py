"""Isolated voice-interface prototype for clinical-ops-copilot.

This package is a thin, additive layer on top of the existing agent. It does
NOT modify the agent, MCP wiring, or any production code. It only:

  1. transcribes an audio question (OpenAI Whisper API, ``whisper-1``),
  2. routes the transcript to a case ID,
  3. runs that case through the EXISTING agent unchanged
     (``agent.runner.run_case`` via ``StdioMcpHost`` + ``AnthropicPlanner``),
  4. speaks the agent's decision with the macOS ``say`` command.

Prototype scope only: file-in / spoken-out, no telephony, no streaming.
"""
