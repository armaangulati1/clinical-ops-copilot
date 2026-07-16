"""FastAPI webhook app for the Twilio Programmable Voice prior-auth interface.

Call flow (one inbound phone call):

    Caller dials the Twilio number
        -> Twilio POSTs  /voice/incoming
        -> we return TwiML <Gather input="speech"> asking for the case number
        -> caller says e.g. "case three, what is the prior auth status"
        -> Twilio transcribes it and POSTs the text to  /voice/decision
        -> we route the transcript to an existing case id, start the UNCHANGED
           agent in the background, and hold the caller with a short message
        -> Twilio re-POSTs  /voice/decision  after a brief pause (a poll); once
           the agent has decided we return TwiML <Say> with the decision + a
           one-line rationale, otherwise we hold again.
        -> Twilio reads the final answer back to the caller.

Why hold-and-poll: a full agent decision takes roughly as long as Twilio's hard
15-second webhook timeout, so answering the first request synchronously makes
the caller hear "an application error has occurred". Instead the first request
returns immediately with a hold message and a <Redirect>; Twilio re-POSTs on
that redirect, and we hand back the decision on whichever poll finds the
background task finished. The agent path itself is unchanged; only the timing of
when we speak the answer moves.

Both endpoints reject any request whose ``X-Twilio-Signature`` does not
validate against the account auth token (and reject unsigned requests), so the
public webhook only ever acts on genuine Twilio traffic.

Honesty scope (same fence as the parent repo): synthetic cases only; the phone
leg routes by case number exactly like the file-in prototype; the agent makes
100% of the decision. Designed to run on a Twilio trial number, so the
trial-message preamble plays before the call connects (expected, disclosed).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

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

# Seconds Twilio pauses (silently) before re-POSTing the <Redirect> poll. Kept
# short so the caller is polled several times inside a single agent decision.
_HOLD_PAUSE_SECONDS = 4
# Maximum number of "still working" holds before we give up and apologize. At
# roughly _HOLD_PAUSE_SECONDS per hold this bounds the caller's wait; the agent
# normally finishes well within it.
_POLL_CAP = 6

_GREETING = (
    "Welcome to the prior authorization assistant. "
    "After the tone, say the case number and your question. "
    "For example, say: case three, what is the prior authorization status."
)
_NO_INPUT = "Sorry, I did not catch a case number. Goodbye."
_STILL_WORKING = "Still working, one moment."
_AGENT_ERROR = (
    "Sorry, something went wrong while looking up that case. Please call again."
)
_CAP_APOLOGY = (
    "Sorry, this is taking longer than expected. Please call again in a few minutes."
)


@dataclass
class _PendingCall:
    """One in-flight agent decision, tracked per Twilio ``CallSid``.

    ``task`` is the background agent run; ``polls`` counts how many "still
    working" holds we have already sent for this call so we can cap the wait.
    """

    task: asyncio.Task[Decision]
    case_id: str
    polls: int = field(default=0)


def _spoken_case(case_id: str) -> str:
    """Render ``case-003`` as ``case 3`` for a natural hold message."""
    tail = case_id.rsplit("-", 1)[-1]
    try:
        return f"case {int(tail)}"
    except ValueError:
        return case_id.replace("-", " ")


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

    # In-flight agent decisions, keyed by Twilio CallSid. A plain dict is safe
    # because the webhook runs as a single-process uvicorn deployment (one event
    # loop); it would need a shared store to scale to multiple workers. Entries
    # are removed on completion, error, and cap-exhaustion so nothing leaks.
    pending: dict[str, _PendingCall] = {}

    def _hold_response(case_id: str) -> Response:
        """First-hit TwiML: greet with a hold message, pause, then poll back."""
        response = VoiceResponse()
        response.say(f"Looking up {_spoken_case(case_id)} now. One moment.")
        response.pause(length=_HOLD_PAUSE_SECONDS)
        response.redirect(config.callback_url(DECISION_PATH), method="POST")
        return _twiml(response)

    def _poll_response(call_sid: str, call: _PendingCall) -> Response:
        """Poll TwiML for a call already running in the background.

        Speaks the decision if the agent has finished (or a clean spoken message
        on a not-found case / any unexpected error), holds again if it is still
        working, and apologizes once the hold cap is exhausted. Every terminal
        branch removes the registry entry.
        """
        if call.task.done():
            del pending[call_sid]
            response = VoiceResponse()
            try:
                agent_decision = call.task.result()
            except CaseNotFoundError:
                response.say(
                    f"I could not find {call.case_id.replace('-', ' ')}. "
                    "Please call again and say a valid case number."
                )
                return _twiml(response)
            except Exception:  # never surface a 500 to the caller
                response.say(_AGENT_ERROR)
                return _twiml(response)
            response.say(spoken_answer(call.case_id, agent_decision))
            return _twiml(response)

        call.polls += 1
        if call.polls > _POLL_CAP:
            call.task.cancel()
            del pending[call_sid]
            response = VoiceResponse()
            response.say(_CAP_APOLOGY)
            return _twiml(response)

        response = VoiceResponse()
        response.say(_STILL_WORKING)
        response.pause(length=_HOLD_PAUSE_SECONDS)
        response.redirect(config.callback_url(DECISION_PATH), method="POST")
        return _twiml(response)

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

        # Twilio re-POSTs on our <Redirect>, so a known CallSid means this is a
        # poll for an already-running decision. Check the registry FIRST: these
        # polls may arrive with no SpeechResult (or a stale one), so keying off
        # the CallSid must take precedence over the empty-transcript branch.
        call_sid = params.get("CallSid", "").strip()
        in_flight = pending.get(call_sid) if call_sid else None
        if in_flight is not None:
            return _poll_response(call_sid, in_flight)

        transcript = params.get("SpeechResult", "").strip()
        if not transcript:
            response = VoiceResponse()
            response.say(_NO_INPUT)
            return _twiml(response)

        # First hit: route the transcript to a case id and start the UNCHANGED
        # agent as a background task. Hold the caller instead of blocking, so we
        # answer well inside Twilio's 15-second webhook timeout.
        case_id = case_id_from_transcript(transcript)
        task: asyncio.Task[Decision] = asyncio.ensure_future(decider(case_id))
        pending[call_sid] = _PendingCall(task=task, case_id=case_id)
        return _hold_response(case_id)

    return app
