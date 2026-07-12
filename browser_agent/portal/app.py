"""Synthetic demo payer portal served with FastAPI.

Two pages:
  GET  /            login form (demo credentials from env, with defaults)
  POST /login       validates credentials, sets an auth cookie, redirects
  GET  /lookup      authorization-status lookup form (requires the cookie)
  POST /lookup      renders the status for a case id from cases.json

The credentials are demo values. The case data is synthetic and mirrors the
case ids used by the OCR eval fixtures. Every page carries a synthetic-demo
banner. This is NOT a real payer portal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

CASES_PATH = Path(__file__).parent / "cases.json"

DEMO_USER = os.environ.get("DEMO_PORTAL_USER", "analyst")
DEMO_PASSWORD = os.environ.get("DEMO_PORTAL_PASSWORD", "demo-password")

AUTH_COOKIE = "portal_auth"
AUTH_VALUE = "demo-session"

_BANNER = (
    '<div style="background:#fde68a;padding:8px;border:1px solid #d97706;'
    'font-family:sans-serif;font-size:13px">SYNTHETIC DEMO PORTAL - '
    "synthetic data only, not a real payer system, no PHI.</div>"
)


def _load_cases() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return data


def _page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><title>{title}</title></head>"
        f'<body style="font-family:sans-serif;max-width:640px;margin:40px auto">'
        f"{_BANNER}<h2>{title}</h2>{body}</body></html>"
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Synthetic Demo Payer Portal")
    cases = _load_cases()

    @app.get("/", response_class=HTMLResponse)
    def login_form() -> str:
        body = (
            '<form method="post" action="/login">'
            '<p><label>Username <input name="username" '
            'data-testid="username"></label></p>'
            '<p><label>Password <input name="password" type="password" '
            'data-testid="password"></label></p>'
            '<button type="submit" data-testid="login">Sign in</button>'
            "</form>"
            f"<p style='color:#555;font-size:12px'>Demo credentials: "
            f"{DEMO_USER} / {DEMO_PASSWORD}</p>"
        )
        return _page("Payer Portal Login", body)

    @app.post("/login", response_model=None)
    def login(
        username: str = Form(...), password: str = Form(...)
    ) -> RedirectResponse | HTMLResponse:
        if username == DEMO_USER and password == DEMO_PASSWORD:
            resp = RedirectResponse(url="/lookup", status_code=303)
            resp.set_cookie(AUTH_COOKIE, AUTH_VALUE, httponly=True)
            return resp
        body = (
            '<p data-testid="login-error" style="color:#b91c1c">'
            "Invalid credentials.</p>"
            '<p><a href="/">Back to login</a></p>'
        )
        return HTMLResponse(_page("Login Failed", body), status_code=401)

    @app.get("/lookup", response_class=HTMLResponse)
    def lookup_form(request: Request) -> HTMLResponse:
        if request.cookies.get(AUTH_COOKIE) != AUTH_VALUE:
            return HTMLResponse(
                _page(
                    "Not Authenticated",
                    '<p data-testid="auth-error">Please '
                    '<a href="/">sign in</a> first.</p>',
                ),
                status_code=401,
            )
        body = (
            '<form method="post" action="/lookup">'
            '<p><label>Case ID <input name="case_id" '
            'data-testid="case-id"></label></p>'
            '<button type="submit" data-testid="lookup">Look up status</button>'
            "</form>"
        )
        return HTMLResponse(_page("Authorization Status Lookup", body))

    @app.post("/lookup", response_class=HTMLResponse)
    def lookup(request: Request, case_id: str = Form(...)) -> HTMLResponse:
        if request.cookies.get(AUTH_COOKIE) != AUTH_VALUE:
            return HTMLResponse(
                _page(
                    "Not Authenticated",
                    '<p data-testid="auth-error">Please '
                    '<a href="/">sign in</a> first.</p>',
                ),
                status_code=401,
            )
        case_id = case_id.strip()
        record = cases.get(case_id)
        if record is None:
            body = (
                f'<p data-testid="not-found" data-case-id="{case_id}">'
                f"No authorization found for case {case_id}.</p>"
                '<p><a href="/lookup">Look up another</a></p>'
            )
            return HTMLResponse(_page("Case Not Found", body), status_code=404)
        auth = record["auth_number"] or "-"
        body = (
            '<table data-testid="status-table" border="1" cellpadding="6">'
            f'<tr><td>Case ID</td><td data-testid="result-case-id">'
            f"{case_id}</td></tr>"
            f'<tr><td>Status</td><td data-testid="result-status">'
            f"{record['decision']}</td></tr>"
            f"<tr><td>Authorization Number</td>"
            f'<td data-testid="result-auth">{auth}</td></tr>'
            "</table>"
            '<p><a href="/lookup">Look up another</a></p>'
        )
        return HTMLResponse(_page("Authorization Status", body))

    return app


app = create_app()
