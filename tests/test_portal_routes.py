"""CI-safe tests for the synthetic demo portal (TestClient, no browser)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from browser_agent.portal.app import (
    AUTH_COOKIE,
    AUTH_VALUE,
    DEMO_PASSWORD,
    DEMO_USER,
    create_app,
)


def _client() -> TestClient:
    return TestClient(create_app())


def test_login_page_renders_synthetic_banner() -> None:
    r = _client().get("/")
    assert r.status_code == 200
    assert "SYNTHETIC DEMO PORTAL" in r.text
    assert 'data-testid="username"' in r.text


def test_login_success_sets_cookie_and_redirects() -> None:
    client = TestClient(create_app(), follow_redirects=False)
    r = client.post("/login", data={"username": DEMO_USER, "password": DEMO_PASSWORD})
    assert r.status_code == 303
    assert r.headers["location"] == "/lookup"
    assert AUTH_COOKIE in r.cookies


def test_login_failure_returns_401() -> None:
    r = _client().post("/login", data={"username": "x", "password": "y"})
    assert r.status_code == 401
    assert "login-error" in r.text


def test_lookup_requires_auth() -> None:
    r = _client().get("/lookup")
    assert r.status_code == 401
    assert "auth-error" in r.text


def test_lookup_found_returns_status() -> None:
    client = _client()
    client.cookies.set(AUTH_COOKIE, AUTH_VALUE)
    r = client.post("/lookup", data={"case_id": "PA-2026-0042"})
    assert r.status_code == 200
    assert "APPROVED" in r.text
    assert "AUTH-8871245" in r.text


def test_lookup_unknown_case_returns_404() -> None:
    client = _client()
    client.cookies.set(AUTH_COOKIE, AUTH_VALUE)
    r = client.post("/lookup", data={"case_id": "PA-9999-9999"})
    assert r.status_code == 404
    assert "not-found" in r.text


def test_portal_cases_match_ocr_ground_truth() -> None:
    # The portal's case ids must stay consistent with the OCR eval fixtures.
    portal = json.loads(
        (
            Path(__file__).parent.parent / "browser_agent" / "portal" / "cases.json"
        ).read_text()
    )
    ocr_gt = json.loads(
        (
            Path(__file__).parent.parent / "ocr" / "fixtures" / "ground_truth.json"
        ).read_text()
    )
    ocr_by_case = {row["case_id"]: row for row in ocr_gt}
    assert set(portal.keys()) == set(ocr_by_case.keys())
    for case_id, rec in portal.items():
        assert rec["decision"] == ocr_by_case[case_id]["decision"]
        assert rec["auth_number"] == ocr_by_case[case_id]["auth_number"]
