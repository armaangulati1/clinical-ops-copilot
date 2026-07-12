"""Playwright agent that drives the synthetic demo portal.

The agent logs in, navigates to the lookup page, submits a case id, and reads
the resulting status from the DOM into a structured ``PortalStatus``. Failures
(wrong password, unknown case, portal unreachable) raise structured errors so
callers get typed outcomes rather than raw Playwright exceptions.

Demo-scope: the only site this agent ever touches is the local synthetic portal
in ``browser_agent.portal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)
from playwright.sync_api import (
    sync_playwright,
)

DEFAULT_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class PortalStatus:
    """Structured result of a single authorization-status lookup."""

    case_id: str
    found: bool
    status: str | None
    auth_number: str | None


class PortalError(RuntimeError):
    """Portal unreachable or returned an unexpected page."""


class LoginError(PortalError):
    """Login failed (bad credentials)."""


class CaseNotFound(PortalError):
    """The portal reported no authorization for the case id."""


class PortalAgent:
    """Drives the synthetic portal. Use as a context manager."""

    def __init__(
        self,
        base_url: str,
        *,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout_ms = timeout_ms

    def __enter__(self) -> PortalAgent:
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=self.headless)
        except PlaywrightError as exc:  # pragma: no cover - env dependent
            self._pw.stop()
            raise PortalError(f"could not launch browser: {exc}") from exc
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *exc: object) -> None:
        self._browser.close()
        self._pw.stop()

    def login(self, username: str, password: str) -> None:
        page = self._page
        try:
            page.goto(f"{self.base_url}/", wait_until="load")
        except PlaywrightError as exc:
            raise PortalError(f"portal unreachable at {self.base_url}") from exc
        page.fill('[data-testid="username"]', username)
        page.fill('[data-testid="password"]', password)
        page.click('[data-testid="login"]')
        page.wait_for_load_state("load")
        if page.query_selector('[data-testid="login-error"]') is not None:
            raise LoginError("invalid portal credentials")
        # A successful login lands on the lookup form.
        page.wait_for_selector('[data-testid="case-id"]')

    def lookup(self, case_id: str) -> PortalStatus:
        page = self._page
        page.goto(f"{self.base_url}/lookup", wait_until="load")
        page.fill('[data-testid="case-id"]', case_id)
        page.click('[data-testid="lookup"]')
        page.wait_for_load_state("load")
        if page.query_selector('[data-testid="not-found"]') is not None:
            raise CaseNotFound(f"no authorization for case {case_id}")
        try:
            page.wait_for_selector('[data-testid="status-table"]')
        except PlaywrightTimeoutError as exc:
            raise PortalError(f"unexpected portal response for case {case_id}") from exc
        status = page.inner_text('[data-testid="result-status"]').strip()
        auth_raw = page.inner_text('[data-testid="result-auth"]').strip()
        result_case = page.inner_text('[data-testid="result-case-id"]').strip()
        return PortalStatus(
            case_id=result_case,
            found=True,
            status=status,
            auth_number=None if auth_raw in ("", "-") else auth_raw,
        )

    def screenshot(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path))
