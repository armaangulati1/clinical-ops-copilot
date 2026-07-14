"""Twilio request-signature validation for the voice webhook.

Every request Twilio sends to a webhook carries an ``X-Twilio-Signature``
header: an HMAC-SHA1 of the exact request URL plus the POST parameters, keyed
by the account's auth token. Validating it proves the request genuinely came
from Twilio (and was not tampered with), which is the only thing standing
between a public webhook and anyone on the internet POSTing forged calls.

We implement Twilio's documented algorithm directly (HMAC-SHA1 over
``url + concat(sorted(key + value))``, base64-encoded) so the security-critical
path has ZERO runtime dependency on the Twilio SDK and is fully verifiable
offline. A parity test cross-checks this against
``twilio.request_validator.RequestValidator`` to prove the two agree byte for
byte.

Reference: https://www.twilio.com/docs/usage/security#validating-requests
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping


def compute_signature(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    """Return the base64 HMAC-SHA1 signature Twilio would send for this request.

    ``url`` must be the full, public URL Twilio used (scheme + host + path,
    including any query string), and ``params`` the application/x-www-form-
    urlencoded POST body. Keys are concatenated in sorted order with their
    values, appended to the URL, then HMAC-SHA1'd with the auth token.
    """
    payload = url
    for key in sorted(params):
        payload += key + params[key]
    digest = hmac.new(
        auth_token.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def is_valid_signature(
    auth_token: str,
    signature: str | None,
    url: str,
    params: Mapping[str, str],
) -> bool:
    """Constant-time check that ``signature`` matches this request.

    Returns ``False`` for a missing/empty signature rather than raising, so the
    webhook can reject unsigned requests with a plain 403.
    """
    if not signature:
        return False
    expected = compute_signature(auth_token, url, params)
    return hmac.compare_digest(expected, signature)
