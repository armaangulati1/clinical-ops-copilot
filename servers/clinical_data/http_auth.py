"""Bearer token authentication for the clinical-data HTTP server."""

from __future__ import annotations

import os
import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

AUTH_TOKEN_ENV = "CLINICAL_DATA_AUTH_TOKEN"
PUBLIC_PATHS = frozenset({"/health", "/metrics"})


def load_auth_token() -> str:
    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if not token:
        msg = f"{AUTH_TOKEN_ENV} must be set for HTTP transport"
        raise RuntimeError(msg)
    return token


def _extract_bearer_token(scope: Scope) -> str | None:
    headers = dict(scope.get("headers", []))
    raw = headers.get(b"authorization")
    if raw is None:
        return None
    value = raw.decode("latin-1")
    prefix = "bearer "
    if not value.lower().startswith(prefix):
        return None
    token: str = value[len(prefix) :].strip()
    return token or None


class BearerTokenMiddleware:
    """Reject unauthenticated access to MCP HTTP endpoints."""

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        self.app = app
        self._expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        provided = _extract_bearer_token(scope)
        if provided is None or not secrets.compare_digest(
            provided, self._expected_token
        ):
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def wrap_with_bearer_auth(app: ASGIApp, expected_token: str | None = None) -> ASGIApp:
    token = expected_token or load_auth_token()
    return BearerTokenMiddleware(app, token)
