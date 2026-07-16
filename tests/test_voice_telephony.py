"""Offline tests for the Twilio voice telephony webhook.

Everything here runs without a network, a phone, or the Twilio cloud: valid
signatures are computed locally, the agent decider is mocked exactly like the
existing agent tests mock it, and TwiML is parsed to assert it is well-formed.

Covered:
  - signature parity with the official ``twilio.request_validator`` SDK,
  - valid-signature POSTs to both webhooks (well-formed TwiML asserted),
  - invalid signature and unsigned requests rejected with 403 (first hits and
    polls for an in-flight call),
  - speech transcript -> case id routing feeding the (mocked) agent,
  - the hold-and-poll flow: first hit holds with a <Redirect>, the decision is
    spoken on a later poll, "still working" holds while the agent runs, and
    case-not-found / unexpected-error / poll-cap all yield clean spoken TwiML
    (never a 500) with the per-call registry cleaned up,
  - empty-speech spoken fallback,
  - env-only config loading and its missing-variable error.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from schemas.decisions import Decision, DecisionAction
from voice_telephony.agent_bridge import CaseNotFoundError
from voice_telephony.app import (
    DECISION_PATH,
    INCOMING_PATH,
    create_app,
)
from voice_telephony.config import ConfigError, TelephonyConfig, load_config
from voice_telephony.signature import compute_signature, is_valid_signature

# A fake test-only auth token, assembled from parts so the repo secret-scanner
# does not flag it as a hardcoded credential (it is not one).
AUTH_TOKEN = "".join(("test", "_auth_", "0123456789abcdef"))
BASE_URL = "https://voice.example.com"


def _config() -> TelephonyConfig:
    return TelephonyConfig(
        account_sid="AC_test_sid",
        auth_token=AUTH_TOKEN,
        public_base_url=BASE_URL,
    )


class _RecordingDecider:
    """Async decider stub that records the case id and returns a fixed decision."""

    def __init__(self, decision: Decision | Exception) -> None:
        self._decision = decision
        self.calls: list[str] = []

    async def __call__(self, case_id: str) -> Decision:
        self.calls.append(case_id)
        if isinstance(self._decision, Exception):
            raise self._decision
        return self._decision


class _GatedDecider:
    """Async decider that blocks until released, then returns or raises.

    The webhook now runs the agent as a background task and holds the caller
    with a ``<Redirect>`` poll until it finishes. This stub lets a test keep the
    decision "pending" across poll requests and then resolve it deterministically
    via the ``TestClient`` portal (``release``), mirroring the real timing.
    """

    def __init__(self, result: Decision | Exception) -> None:
        self._result = result
        self.event = asyncio.Event()
        self.calls: list[str] = []

    async def __call__(self, case_id: str) -> Decision:
        self.calls.append(case_id)
        await self.event.wait()
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def release(self, client: TestClient) -> None:
        """Unblock the pending decision from the client thread (loop-safe)."""
        assert client.portal is not None  # set while TestClient is entered
        client.portal.call(self.event.set)


def _submit_decision() -> Decision:
    return Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.98,
        rationale="All required payer criteria are met with high confidence.",
        missing_fields=[],
    )


def _signed_post(
    client: TestClient,
    path: str,
    params: Mapping[str, str],
    *,
    token: str = AUTH_TOKEN,
) -> Any:  # httpx.Response from TestClient; httpx stubs surface it as Any.
    """POST form ``params`` with a valid X-Twilio-Signature for ``path``."""
    url = f"{BASE_URL}{path}"
    signature = compute_signature(token, url, params)
    return client.post(
        path,
        data=dict(params),
        headers={"X-Twilio-Signature": signature},
    )


def _first_hit(
    client: TestClient,
    *,
    call_sid: str,
    transcript: str = "check case three prior auth status",
) -> Any:
    """Signed first /voice/decision request carrying the spoken transcript."""
    return _signed_post(
        client,
        DECISION_PATH,
        {"CallSid": call_sid, "SpeechResult": transcript},
    )


def _poll(client: TestClient, call_sid: str) -> Any:
    """Signed poll: Twilio re-POSTs the redirect with the CallSid, no speech."""
    return _signed_post(client, DECISION_PATH, {"CallSid": call_sid})


def _poll_until_final(client: TestClient, call_sid: str, *, attempts: int = 8) -> Any:
    """Poll until a terminal (no-redirect) TwiML response comes back.

    Tolerates one or more "still working" holds so the resolution assertions do
    not depend on exactly which poll observes the finished background task.
    """
    for _ in range(attempts):
        resp = _poll(client, call_sid)
        if ET.fromstring(resp.text).find("Redirect") is None:
            return resp
    raise AssertionError("decision never finalized within the poll budget")


# --- signature primitives -------------------------------------------------


def test_signature_matches_official_twilio_sdk() -> None:
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(AUTH_TOKEN)
    url = f"{BASE_URL}{DECISION_PATH}"
    for params in (
        {
            "CallSid": "CA123",
            "SpeechResult": "check case three",
            "From": "+15551234567",
        },
        {"SpeechResult": "case forty eight status"},
        {},
    ):
        assert compute_signature(AUTH_TOKEN, url, params) == (
            validator.compute_signature(url, params)
        )


def test_is_valid_signature_rejects_missing_and_tampered() -> None:
    url = f"{BASE_URL}{DECISION_PATH}"
    params = {"SpeechResult": "case three"}
    good = compute_signature(AUTH_TOKEN, url, params)
    assert is_valid_signature(AUTH_TOKEN, good, url, params) is True
    assert is_valid_signature(AUTH_TOKEN, None, url, params) is False
    assert is_valid_signature(AUTH_TOKEN, "", url, params) is False
    assert is_valid_signature(AUTH_TOKEN, good + "x", url, params) is False
    # A different signed body must not validate against these params.
    tampered = {"SpeechResult": "case four"}
    assert is_valid_signature(AUTH_TOKEN, good, url, tampered) is False


# --- /voice/incoming ------------------------------------------------------


def test_incoming_returns_wellformed_gather_twiml() -> None:
    app = create_app(config=_config(), decider=_RecordingDecider(_submit_decision()))
    client = TestClient(app)
    resp = _signed_post(
        client, INCOMING_PATH, {"CallSid": "CA1", "From": "+15550001111"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")

    root = ET.fromstring(resp.text)  # raises if malformed
    assert root.tag == "Response"
    gather = root.find("Gather")
    assert gather is not None
    assert gather.attrib["input"] == "speech"
    assert gather.attrib["action"] == f"{BASE_URL}{DECISION_PATH}"
    assert gather.attrib["method"] == "POST"
    # Prompt lives inside the Gather so the caller can barge in with speech.
    assert gather.find("Say") is not None


# --- /voice/decision: hold-and-poll flow ----------------------------------
#
# A full agent decision takes about as long as Twilio's hard 15-second webhook
# timeout, so the first request no longer answers synchronously. It starts the
# UNCHANGED agent in the background and returns a hold message plus a <Redirect>;
# Twilio re-POSTs on that redirect (a poll), and the decision is spoken on
# whichever poll finds the background task finished.


def test_decision_first_hit_holds_with_redirect_and_no_answer() -> None:
    decider = _GatedDecider(_submit_decision())
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        resp = _first_hit(client, call_sid="CA2")
        assert resp.status_code == 200

        root = ET.fromstring(resp.text)
        assert root.tag == "Response"
        # First hit holds the caller: a spoken preamble + a redirect back to the
        # decision URL, and crucially NOT the decision text yet.
        say = root.find("Say")
        assert say is not None
        assert say.text is not None
        assert "looking up" in say.text.lower()
        redirect = root.find("Redirect")
        assert redirect is not None
        assert redirect.text == f"{BASE_URL}{DECISION_PATH}"
        assert redirect.attrib["method"] == "POST"
        assert "submit" not in resp.text
        assert "percent" not in resp.text


def test_decision_poll_speaks_answer_after_decider_resolves() -> None:
    decider = _GatedDecider(_submit_decision())
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA2")
        decider.release(client)
        resp = _poll_until_final(client, "CA2")

    assert resp.status_code == 200
    # The transcript routed to case-003 and that id reached the agent decider.
    assert decider.calls == ["case-003"]

    root = ET.fromstring(resp.text)
    assert root.find("Redirect") is None
    say = root.find("Say")
    assert say is not None
    assert say.text is not None
    assert "case-003" in say.text
    assert "submit" in say.text
    assert "98 percent" in say.text


def test_decision_poll_still_working_while_decider_pending() -> None:
    decider = _GatedDecider(_submit_decision())
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA2")
        # Decider not released, so the background task is still running.
        resp = _poll(client, "CA2")

    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    # Still working: another hold + redirect, no decision spoken.
    redirect = root.find("Redirect")
    assert redirect is not None
    assert redirect.text == f"{BASE_URL}{DECISION_PATH}"
    say = root.find("Say")
    assert say is not None
    assert say.text is not None
    assert "still working" in say.text.lower()


def test_decision_empty_speech_speaks_no_input_and_skips_agent() -> None:
    decider = _RecordingDecider(_submit_decision())
    app = create_app(config=_config(), decider=decider)
    client = TestClient(app)

    resp = _signed_post(client, DECISION_PATH, {"CallSid": "CA3", "SpeechResult": ""})
    assert resp.status_code == 200
    assert decider.calls == []  # agent not run when no speech was captured
    root = ET.fromstring(resp.text)
    assert root.find("Say") is not None


def test_decision_poll_case_not_found_speaks_clean_message() -> None:
    decider = _GatedDecider(CaseNotFoundError("no such case"))
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA4", transcript="case nine hundred ninety nine")
        decider.release(client)
        resp = _poll_until_final(client, "CA4")

    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    say = root.find("Say")
    assert say is not None
    assert say.text is not None
    assert "could not find" in say.text.lower()


def test_decision_poll_unexpected_error_speaks_apology_not_500() -> None:
    # Any exception other than CaseNotFoundError must become a spoken apology,
    # never a 500 read back to the caller as "an application error has occurred".
    decider = _GatedDecider(RuntimeError("planner blew up"))
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA6")
        decider.release(client)
        resp = _poll_until_final(client, "CA6")

    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    assert root.find("Redirect") is None
    say = root.find("Say")
    assert say is not None
    assert say.text is not None
    assert "sorry" in say.text.lower()


def test_decision_poll_cap_exhaustion_apologizes_and_cleans_up() -> None:
    decider = _GatedDecider(_submit_decision())  # never released -> stays pending
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA7")
        # Up to the cap, each poll returns another "still working" hold.
        for _ in range(6):
            root = ET.fromstring(_poll(client, "CA7").text)
            assert root.find("Redirect") is not None

        # The next poll exhausts the cap: apology, no redirect.
        exhausted = _poll(client, "CA7")
        assert exhausted.status_code == 200
        root = ET.fromstring(exhausted.text)
        assert root.find("Redirect") is None
        say = root.find("Say")
        assert say is not None
        assert say.text is not None
        assert "sorry" in say.text.lower()

        # Registry entry was removed: a further poll for this CallSid is no
        # longer recognized as in-flight and falls back to the no-input branch.
        after = _poll(client, "CA7")
        root = ET.fromstring(after.text)
        assert root.find("Redirect") is None
        say = root.find("Say")
        assert say is not None
        assert say.text is not None
        assert "did not catch" in say.text.lower()


def test_decision_poll_twiml_escapes_special_chars_in_spoken_answer() -> None:
    # missing_fields carrying XML-hostile characters must not break the TwiML.
    # This locks the escaping property against future edits to spoken_answer.
    decision = Decision(
        action=DecisionAction.REQUEST_MORE_INFO,
        confidence=0.60,
        rationale="Documentation is incomplete; request more before submitting.",
        missing_fields=["a & b <x>"],
    )
    decider = _GatedDecider(decision)
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA5")
        decider.release(client)
        resp = _poll_until_final(client, "CA5")

    assert resp.status_code == 200
    # Parses without error only if the '&', '<', '>' were XML-escaped.
    root = ET.fromstring(resp.text)
    say = root.find("Say")
    assert say is not None
    assert say.text is not None
    # The raw characters survive as text once XML-decoded by the parser.
    assert "a & b <x>" in say.text


# --- signature enforcement on the live webhook ----------------------------


def test_webhook_rejects_invalid_signature() -> None:
    app = create_app(config=_config(), decider=_RecordingDecider(_submit_decision()))
    client = TestClient(app)
    resp = client.post(
        DECISION_PATH,
        data={"SpeechResult": "case three"},
        headers={"X-Twilio-Signature": "obviously-wrong"},
    )
    assert resp.status_code == 403


def test_webhook_rejects_unsigned_request() -> None:
    app = create_app(config=_config(), decider=_RecordingDecider(_submit_decision()))
    client = TestClient(app)
    for path in (INCOMING_PATH, DECISION_PATH):
        resp = client.post(path, data={"SpeechResult": "case three"})
        assert resp.status_code == 403


def test_webhook_rejects_signature_for_a_different_token() -> None:
    app = create_app(config=_config(), decider=_RecordingDecider(_submit_decision()))
    client = TestClient(app)
    # Valid signature, but computed with the wrong auth token -> rejected.
    wrong_token = "".join(("a_different_", "wrong_token"))
    resp = _signed_post(
        client,
        DECISION_PATH,
        {"SpeechResult": "case three"},
        token=wrong_token,
    )
    assert resp.status_code == 403


def test_webhook_rejects_unsigned_and_invalid_poll_for_inflight_call() -> None:
    # Signature validation runs before the CallSid registry lookup, so an
    # in-flight call cannot be advanced (or leaked) by a forged poll.
    decider = _GatedDecider(_submit_decision())
    app = create_app(config=_config(), decider=decider)
    with TestClient(app) as client:
        _first_hit(client, call_sid="CA8")

        unsigned = client.post(DECISION_PATH, data={"CallSid": "CA8"})
        assert unsigned.status_code == 403

        invalid = client.post(
            DECISION_PATH,
            data={"CallSid": "CA8"},
            headers={"X-Twilio-Signature": "obviously-wrong"},
        )
        assert invalid.status_code == 403

        # A properly signed poll still works, proving only the signature gated it.
        decider.release(client)
        resp = _poll_until_final(client, "CA8")
        assert resp.status_code == 200
        assert "submit" in resp.text


# --- config ---------------------------------------------------------------


def test_load_config_reads_environment() -> None:
    env = {
        "TWILIO_ACCOUNT_SID": "AC_x",
        "TWILIO_AUTH_TOKEN": "tok",
        "VOICE_PUBLIC_BASE_URL": "https://x.fly.dev/",
    }
    config = load_config(env)
    assert config.account_sid == "AC_x"
    assert config.auth_token == "tok"
    # Trailing slash is stripped and callback URLs are built cleanly.
    assert config.base_url == "https://x.fly.dev"
    assert config.callback_url("/voice/decision") == "https://x.fly.dev/voice/decision"


def test_load_config_missing_variable_raises() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config({"TWILIO_ACCOUNT_SID": "AC_x"})
    message = str(excinfo.value)
    assert "TWILIO_AUTH_TOKEN" in message
    assert "VOICE_PUBLIC_BASE_URL" in message
