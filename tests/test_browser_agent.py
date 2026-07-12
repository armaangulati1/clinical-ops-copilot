"""Chromium-dependent browser-agent tests.

Marked ``browser`` and excluded from the CI gate. They also self-skip when a
Playwright chromium build is not installed, so a local run without chromium
degrades gracefully.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from browser_agent.agent import (
    CaseNotFound,
    LoginError,
    PortalAgent,
    PortalStatus,
)
from browser_agent.demo import run_demo, run_portal
from browser_agent.portal.app import DEMO_PASSWORD, DEMO_USER


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        not _chromium_available(),
        reason="Playwright chromium not installed",
    ),
]


def test_agent_login_and_lookup_roundtrip() -> None:
    with run_portal() as base_url, PortalAgent(base_url) as agent:
        agent.login(DEMO_USER, DEMO_PASSWORD)
        result = agent.lookup("PA-2026-0042")
        assert isinstance(result, PortalStatus)
        assert result.status == "APPROVED"
        assert result.auth_number == "AUTH-8871245"


def test_agent_denied_case_has_no_auth() -> None:
    with run_portal() as base_url, PortalAgent(base_url) as agent:
        agent.login(DEMO_USER, DEMO_PASSWORD)
        result = agent.lookup("PA-2026-0117")
        assert result.status == "DENIED"
        assert result.auth_number is None


def test_agent_bad_password_raises_login_error() -> None:
    with (
        run_portal() as base_url,
        PortalAgent(base_url) as agent,
        pytest.raises(LoginError),
    ):
        agent.login(DEMO_USER, "wrong-password")


def test_agent_unknown_case_raises_case_not_found() -> None:
    with run_portal() as base_url, PortalAgent(base_url) as agent:
        agent.login(DEMO_USER, DEMO_PASSWORD)
        with pytest.raises(CaseNotFound):
            agent.lookup("PA-0000-0000")


def test_full_demo_is_self_consistent() -> None:
    mismatches = run_demo(capture_screenshots=False)
    assert mismatches == 0
