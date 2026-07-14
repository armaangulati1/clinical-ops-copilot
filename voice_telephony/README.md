# voice_telephony: real-telephony voice interface

A phone call in, the agent's decision spoken back out.

```
Caller dials the Twilio number
   -> Twilio POSTs /voice/incoming
   -> <Gather input="speech">  "say the case number and your question"
   -> caller: "case three, what is the prior auth status"
   -> Twilio transcribes the speech, POSTs it to /voice/decision
   -> the transcript routes to an existing case id
   -> the UNCHANGED agent runs that case (planner + MCP tools)
   -> <Say> reads back the decision + one-line rationale
```

This is an additive layer. It reuses the shared `voice` glue (`case_id_from_transcript`,
`spoken_answer`) and the exact `agent.runner.run_case` path that `python -m agent`
and the file-in voice prototype use. It does not modify the agent, the MCP wiring,
the servers, or any other production code.

## What is honest here (scope + fences)

- **Synthetic data only.** Same fence as the parent repo: the cases in `data/cases/`
  are synthetic. No real patient data touches this path.
- **The voice layer only routes and phrases.** It resolves a spoken question to a
  `case-0NN` id and reads the answer aloud. The **agent makes 100% of the decision**;
  the telephony code adds nothing to the reasoning.
- **Case-number routing.** Exactly like the file-in prototype, the phone leg routes
  by case number ("case three" -> `case-003`), not free-form question answering.
- **Twilio trial.** Built and verified on a Twilio trial number, so a short trial
  message ("You have a trial account...") plays before the call connects. That is
  expected and disclosed; it does not affect the agent path.
- **Speech-to-text is Twilio's.** Unlike the Whisper prototype, the STT here is done
  by Twilio's `<Gather input="speech">`. There is no Whisper/OpenAI dependency in this
  module.

## Security: every webhook request is signature-validated

Both endpoints reject any request whose `X-Twilio-Signature` header does not validate
against the account auth token, and reject unsigned requests outright (HTTP 403). The
validation (`voice_telephony/signature.py`) implements Twilio's documented HMAC-SHA1
algorithm directly, so the security-critical path has zero runtime dependency on the
Twilio SDK and is fully testable offline. A test cross-checks it byte-for-byte against
the official `twilio.request_validator.RequestValidator`.

The signed URL is rebuilt from the configured public base URL, not the proxied request
host, so validation is correct behind Fly.io / a tunnel.

## Configuration (environment only, no secrets committed)

| Variable | Purpose |
|----------|---------|
| `TWILIO_ACCOUNT_SID` | Account identifier (informational). |
| `TWILIO_AUTH_TOKEN` | Signs every inbound webhook; validated on each request. |
| `VOICE_PUBLIC_BASE_URL` | Public https origin Twilio calls, e.g. `https://<app>.fly.dev` or `https://<id>.ngrok-free.app`. |

`.env` is gitignored. In production these are set with `fly secrets set`.

## Install (opt-in extra)

The Twilio SDK is the `telephony` optional extra, never a core dependency:

```bash
uv sync --extra telephony
```

(CI installs it via the dev group so the offline webhook tests run.)

## Run

Production ASGI entrypoint (reads config from the environment, wires in the real agent):

```bash
uv run uvicorn voice_telephony.asgi:app --host 0.0.0.0 --port 8080
```

See `RUNBOOK.md` for the full live-call setup (Fly deploy or local + tunnel) and the
exact Twilio console steps.

## Tests

`tests/test_voice_telephony.py` (offline, mocked Twilio + mocked agent decider):
signature parity with the official SDK, valid/invalid/unsigned request handling,
speech-transcript-to-case routing, case-not-found and empty-speech fallbacks, and
well-formed TwiML assertions. `tests/test_voice_glue.py` covers the shared routing +
phrasing. Both run in the standard `pytest -m "not network"` gate.

## Files

- `signature.py`: Twilio HMAC-SHA1 signature validation (dependency-free).
- `config.py`: environment-only `TelephonyConfig` loader.
- `agent_bridge.py`: runs the unchanged agent for one case id.
- `app.py`: `create_app(config, decider)` builds the two signed TwiML webhooks.
- `asgi.py`: `uvicorn voice_telephony.asgi:app` production entrypoint.
- `RUNBOOK.md`: deploy + live-call verification steps.
