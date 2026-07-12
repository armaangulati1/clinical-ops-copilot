"""Round-trip demo: drive the synthetic portal and self-consistency check.

Spins up the local synthetic portal, logs in with the Playwright agent, looks
up a set of case ids, and compares the statuses read from the DOM against the
portal's own source JSON. This is a SELF-CONSISTENCY check: the portal is the
source of truth for its own data, so agreement demonstrates that the agent
navigates and scrapes correctly, not that any external system was validated.

Also captures screenshots of the login, lookup, and result pages into
``browser_agent/evidence/`` for the README.

Run:
    uv run python -m browser_agent.demo
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn

from browser_agent.agent import PortalAgent
from browser_agent.portal.app import DEMO_PASSWORD, DEMO_USER, create_app

EVIDENCE_DIR = Path(__file__).parent / "evidence"
CASES_PATH = Path(__file__).parent / "portal" / "cases.json"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def run_portal() -> Iterator[str]:
    """Start the portal in a background thread; yield its base URL."""
    port = _free_port()
    config = uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            httpx.get(base + "/", timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:  # pragma: no cover - startup failure
        server.should_exit = True
        raise RuntimeError("portal did not start")
    try:
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def run_demo(capture_screenshots: bool = True) -> int:
    """Drive the portal over all case ids; return the mismatch count."""
    source = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case_ids = list(source.keys())
    rows: list[tuple[str, str, str, str]] = []
    mismatches = 0

    with run_portal() as base_url, PortalAgent(base_url) as agent:
        agent.login(DEMO_USER, DEMO_PASSWORD)
        if capture_screenshots:
            agent.screenshot(EVIDENCE_DIR / "02_lookup_form.png")
        for i, case_id in enumerate(case_ids):
            result = agent.lookup(case_id)
            expected = source[case_id]["decision"]
            got = result.status or ""
            ok = got == expected
            if not ok:
                mismatches += 1
            rows.append((case_id, expected, got, "match" if ok else "MISMATCH"))
            if capture_screenshots and i == 0:
                agent.screenshot(EVIDENCE_DIR / "03_status_result.png")
        # Also capture the login page itself for evidence.
        if capture_screenshots:
            agent._page.goto(f"{base_url}/", wait_until="load")
            agent.screenshot(EVIDENCE_DIR / "01_login.png")

    print("Portal round-trip self-consistency (agent DOM vs portal source JSON)")
    print("")
    print(f"{'case_id':<16}{'expected':<11}{'agent-read':<12}{'result'}")
    print("-" * 50)
    for case_id, expected, got, verdict in rows:
        print(f"{case_id:<16}{expected:<11}{got:<12}{verdict}")
    print("-" * 50)
    print(f"{len(rows)} cases, {mismatches} mismatch(es)")
    return mismatches


def main() -> None:
    mismatches = run_demo()
    raise SystemExit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
