"""FastAPI webhook app for the Twilio Programmable Voice prior-auth interface.

Call flow (one inbound phone call):

    Caller dials the Twilio number
        -> Twilio POSTs  /voice/incoming
        -> we return TwiML <Gather input="speech"> asking for the case number
        -> caller says e.g. "case three, what is the prior auth status"
        -> Twilio transcribes it and POSTs the text to  /voice/decision
        -> we route the transcript to an existing case id, run the UNCHANGED
           agent, and return TwiML <Say> with the decision + one-line rationale
        -> Twilio reads it back to the caller.

Both endpoints reject any request whose ``X-Twilio-Signature`` does not
validate against the account auth token (and reject unsigned requests), so the
public webhook only ever acts on genuine Twilio traffic.

Honesty scope (same fence as the parent repo): synthetic cases only; the phone
leg routes by case number exactly like the file-in prototype; the agent makes
100% of the decision. Designed to run on a Twilio trial number, so the
trial-message preamble plays before the call connects (expected, disclosed).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response
from twilio.twiml.voice_response import Gather, VoiceResponse

from schemas.decisions import Decision
from voice.route import case_id_from_transcript
from voice.speak import spoken_answer
from voice_telephony.agent_bridge import CaseNotFoundError
from voice_telephony.config import TelephonyConfig
from voice_telephony.signature import is_valid_signature

INCOMING_PATH = "/voice/incoming"
DECISION_PATH = "/voice/decision"

# ``Callable[[case_id], Decision]``, injected so tests mock the agent exactly
# as the existing agent tests do; production wires in the real agent runner.
Decider = Callable[[str], Awaitable[Decision]]

_TWIML_MEDIA_TYPE = "application/xml"

_GREETING = (
    "Welcome to the prior authorization assistant. "
    "After the tone, say the case number and your question. "
    "For example, say: case three, what is the prior authorization status."
)
_NO_INPUT = "Sorry, I did not catch a case number. Goodbye."


def _twiml(response: VoiceResponse) -> Response:
    return Response(content=str(response), media_type=_TWIML_MEDIA_TYPE)


def _requested_url(config: TelephonyConfig, request: Request) -> str:
    """Rebuild the exact public URL Twilio signed (never trust the proxy host)."""
    url = config.callback_url(request.url.path)
    if request.url.query:
        url = f"{url}?{request.url.query}"
    return url


def create_app(*, config: TelephonyConfig, decider: Decider) -> FastAPI:
    """Build the telephony FastAPI app.

    ``config`` supplies the auth token (for signature validation) and public
    base URL (for the Gather callback + signed-URL reconstruction). ``decider``
    turns a case id into a :class:`Decision`; it is the only seam the tests
    mock.
    """
    app = FastAPI(title="clinical-ops-copilot voice telephony", version="0.1.0")

    async def _signed_form(request: Request) -> dict[str, str] | None:
        """Return the POST params if the Twilio signature is valid, else None."""
        form = await request.form()
        params = {key: str(value) for key, value in form.items()}
        signature = request.headers.get("X-Twilio-Signature")
        url = _requested_url(config, request)
        if not is_valid_signature(config.auth_token, signature, url, params):
            return None
        return params

    @app.post(INCOMING_PATH)
    async def incoming(request: Request) -> Response:
        if await _signed_form(request) is None:
            return Response("Invalid Twilio signature", status_code=403)
        response = VoiceResponse()
        gather = Gather(
            input="speech",
            action=config.callback_url(DECISION_PATH),
            method="POST",
            speech_timeout="auto",
            speech_model="phone_call",
        )
        gather.say(_GREETING)
        response.append(gather)
        # Reached only if the caller says nothing before the Gather times out.
        response.say(_NO_INPUT)
        return _twiml(response)

    @app.post(DECISION_PATH)
    async def decision(request: Request) -> Response:
        params = await _signed_form(request)
        if params is None:
            return Response("Invalid Twilio signature", status_code=403)

        transcript = params.get("SpeechResult", "").strip()
        response = VoiceResponse()
        if not transcript:
            response.say(_NO_INPUT)
            return _twiml(response)

        case_id = case_id_from_transcript(transcript)
        try:
            agent_decision = await decider(case_id)
        except CaseNotFoundError:
            response.say(
                f"I could not find {case_id.replace('-', ' ')}. "
                "Please call again and say a valid case number."
            )
            return _twiml(response)

        response.say(spoken_answer(case_id, agent_decision))
        return _twiml(response)

    return app
