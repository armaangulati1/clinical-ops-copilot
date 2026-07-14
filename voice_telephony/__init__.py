"""Real-telephony voice interface for the prior-auth agent (Twilio webhooks).

A phone call in -> Twilio speech-to-text -> the EXISTING agent's decision ->
spoken reply. This is an additive layer: it reuses the shared ``voice`` glue
(case routing + spoken phrasing) and the unchanged ``agent.runner`` path; it
does not modify the agent, MCP wiring, or any production code.

Opt-in: the Twilio SDK is the ``telephony`` optional extra, never a core
runtime dependency. See ``voice_telephony/README.md`` for scope and
``voice_telephony/RUNBOOK.md`` for the live-call setup.
"""
