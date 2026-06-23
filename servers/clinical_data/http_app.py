"""StreamableHTTP ASGI application for the clinical-data MCP server."""

from __future__ import annotations

import os

import anyio
import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from servers.clinical_data.http_auth import wrap_with_bearer_auth
from servers.clinical_data.http_metrics import METRICS
from servers.clinical_data.http_metrics_middleware import MetricsMiddleware
from servers.clinical_data.server import mcp
from servers.clinical_data.version import __version__

HTTP_HOST_ENV = "CLINICAL_DATA_HTTP_HOST"
HTTP_PORT_ENV = "CLINICAL_DATA_HTTP_PORT"
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8000

_ROUTES_REGISTERED = False


def _register_public_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "uptime_seconds": METRICS.uptime_seconds(),
            }
        )

    @mcp.custom_route("/metrics", methods=["GET"])
    async def metrics(_request: Request) -> JSONResponse:
        return JSONResponse(METRICS.snapshot())

    _ROUTES_REGISTERED = True


def create_http_app(*, auth_token: str | None = None) -> ASGIApp:
    """Build a stateful StreamableHTTP ASGI app with auth and metrics."""
    _register_public_routes()
    # FastMCP defaults: stateless_http=False, json_response=False (SSE preserved).
    app = mcp.streamable_http_app()
    wrapped: ASGIApp = MetricsMiddleware(app)
    return wrap_with_bearer_auth(wrapped, expected_token=auth_token)


def run_http_server(
    *,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
) -> None:
    """Run the clinical-data MCP server over StreamableHTTP."""
    resolved_host = host or os.environ.get(HTTP_HOST_ENV, DEFAULT_HTTP_HOST)
    resolved_port = int(port or os.environ.get(HTTP_PORT_ENV, str(DEFAULT_HTTP_PORT)))
    starlette_app = create_http_app(auth_token=auth_token)

    async def _serve() -> None:
        config = uvicorn.Config(
            starlette_app,
            host=resolved_host,
            port=resolved_port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    anyio.run(_serve)
