"""Environment-only configuration for the telephony webhook.

No secrets are ever committed. The three values below come from the process
environment (loaded from the gitignored ``.env`` locally, or from ``fly secrets``
in production):

  - ``TWILIO_ACCOUNT_SID``: account identifier (informational; not secret).
  - ``TWILIO_AUTH_TOKEN``: signs every inbound webhook; validate against it.
  - ``VOICE_PUBLIC_BASE_URL``: the public https origin Twilio calls, e.g.
    ``https://my-app.fly.dev`` or an ``https://<id>.ngrok-free.app`` tunnel.
    Used both to build the ``<Gather action=...>`` callback URL and to
    reconstruct the exact URL Twilio signed (never trust the proxied
    ``request.url`` host behind Fly/ngrok).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ACCOUNT_SID_ENV = "TWILIO_ACCOUNT_SID"
AUTH_TOKEN_ENV = "TWILIO_AUTH_TOKEN"
PUBLIC_BASE_URL_ENV = "VOICE_PUBLIC_BASE_URL"


@dataclass(frozen=True)
class TelephonyConfig:
    """Resolved telephony settings (all sourced from the environment)."""

    account_sid: str
    auth_token: str
    public_base_url: str

    @property
    def base_url(self) -> str:
        """Public origin with any trailing slash removed."""
        return self.public_base_url.rstrip("/")

    def callback_url(self, path: str) -> str:
        """Absolute public URL for a webhook path (e.g. ``/voice/decision``)."""
        return f"{self.base_url}/{path.lstrip('/')}"


class ConfigError(RuntimeError):
    """Raised when a required telephony environment variable is missing."""


def load_config(environ: dict[str, str] | None = None) -> TelephonyConfig:
    """Build a :class:`TelephonyConfig` from the environment.

    Raises :class:`ConfigError` naming every missing variable, so a misconfigured
    deploy fails loudly at startup instead of silently accepting forged calls.
    """
    env = environ if environ is not None else dict(os.environ)
    missing = [
        name
        for name in (ACCOUNT_SID_ENV, AUTH_TOKEN_ENV, PUBLIC_BASE_URL_ENV)
        if not env.get(name)
    ]
    if missing:
        joined = ", ".join(missing)
        msg = f"Missing required telephony environment variable(s): {joined}"
        raise ConfigError(msg)
    return TelephonyConfig(
        account_sid=env[ACCOUNT_SID_ENV],
        auth_token=env[AUTH_TOKEN_ENV],
        public_base_url=env[PUBLIC_BASE_URL_ENV],
    )
