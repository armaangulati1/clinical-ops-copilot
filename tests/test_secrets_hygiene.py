"""Secrets hygiene checks.

Scope note, earned the hard way on 2026-07-27: a live Anthropic key sat in
``demo_env.sh`` at the repo root and survived this guard, because the guard
scanned six named directories and only ``*.py``. The repo root was not scanned
and ``.sh`` was not a scanned extension. A guard that cannot look where the
secret lives is not a guard.

So the checks below come in two shapes:

* **Everything git tracks**, at any path and any extension, is scanned for a
  real Anthropic key pattern. Tracked content is what a push publishes, so this
  is the check that maps to the actual threat.
* **Untracked files that are not ignored** are scanned too. Those are the files
  one ``git add -A`` away from being tracked, which is exactly what ``demo_env.sh``
  was. A working file holding a key must be gitignored.

The inline-secret-assignment heuristic stays scoped to Python source. It matches
``TOKEN="..."`` shapes, which appear legitimately in the README and deploy docs
as placeholders (``<your key>``, ``$(openssl rand -hex 32)``), so running it over
prose would fail on documentation rather than on secrets.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from agent.audit import InMemoryAuditTrail
from agent.run_log import RunLog, RunLogWriter
from schemas.decisions import Decision, DecisionAction
from schemas.phi_redaction import (
    HARDCODED_KEY_PATTERN,
    scan_for_obvious_secrets_in_source,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("agent", "servers", "schemas", "tests", "ui", "scripts")
SCAN_SKIP_FILES = frozenset({"test_secrets_hygiene.py"})


def _fake_api_key() -> str:
    return "".join(("sk-ant-test-", "secret-value-", "1234567890"))


def _real_key_shaped_value() -> str:
    """A string matching the real-key pattern, built so this file never holds one."""
    return "".join(("sk-", "ant-", "api", "03-", "AbCdEfGhIj0123456789"))


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return files


def _git(*args: str) -> list[str]:
    """Run a git command in the repo, returning its lines (empty if git is absent)."""
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git
        return []
    if result.returncode != 0:  # pragma: no cover - not a git checkout
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _text_or_none(path: Path) -> str | None:
    """Read a file as text, or return None when it is binary or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def test_repo_has_no_hardcoded_api_keys() -> None:
    findings: list[str] = []
    for path in _iter_source_files():
        if path.name in SCAN_SKIP_FILES:
            continue
        source = path.read_text(encoding="utf-8")
        hits = scan_for_obvious_secrets_in_source(source)
        if hits:
            findings.append(f"{path}: {hits}")
    assert findings == [], f"hardcoded secret patterns found: {findings}"


def test_real_key_pattern_actually_matches() -> None:
    """Control: the scan below can fail, so a clean result is real evidence."""
    assert HARDCODED_KEY_PATTERN.search(_real_key_shaped_value())
    assert not HARDCODED_KEY_PATTERN.search("ANTHROPIC_API_KEY=<your key>")


def test_no_real_api_key_in_any_tracked_file() -> None:
    """Every tracked file, any path and any extension, is free of a real key.

    Not just ``*.py`` under six directories: a push publishes whatever git
    tracks, so that is the surface this has to cover.
    """
    tracked = _git("ls-files")
    if not tracked:  # pragma: no cover - not a git checkout
        pytest.skip("not a git checkout; nothing to scan")

    findings: list[str] = []
    scanned = 0
    for name in tracked:
        path = PROJECT_ROOT / name
        if path.name in SCAN_SKIP_FILES or not path.is_file():
            continue
        text = _text_or_none(path)
        if text is None:
            continue
        scanned += 1
        if HARDCODED_KEY_PATTERN.search(text):
            findings.append(name)

    assert scanned > 100, f"only scanned {scanned} files; the guard looks broken"
    assert findings == [], f"real API key pattern in tracked files: {findings}"


def test_untracked_files_holding_a_real_key_are_gitignored() -> None:
    """A working file containing a key must not be one ``git add -A`` from a push.

    This is the exact 2026-07-27 case: ``demo_env.sh`` sat untracked and
    un-ignored at the repo root holding a live key. ``--exclude-standard`` lists
    untracked files that are *not* ignored, which is the stageable set.
    """
    stageable = _git("ls-files", "--others", "--exclude-standard")

    offenders: list[str] = []
    for name in stageable:
        path = PROJECT_ROOT / name
        if path.name in SCAN_SKIP_FILES or not path.is_file():
            continue
        text = _text_or_none(path)
        if text is not None and HARDCODED_KEY_PATTERN.search(text):
            offenders.append(name)

    assert offenders == [], (
        "untracked but stageable files contain a real API key pattern; "
        f"gitignore them or remove the key: {offenders}"
    )


def test_no_inline_secret_assignment_in_tracked_python() -> None:
    """Widens the ``*.py`` scan from six directories to every tracked Python file.

    The repo root was previously invisible to this check.
    """
    tracked = _git("ls-files", "*.py")
    if not tracked:  # pragma: no cover - not a git checkout
        pytest.skip("not a git checkout; nothing to scan")

    findings: list[str] = []
    for name in tracked:
        path = PROJECT_ROOT / name
        if path.name in SCAN_SKIP_FILES or not path.is_file():
            continue
        text = _text_or_none(path)
        if text is None:
            continue
        hits = scan_for_obvious_secrets_in_source(text)
        if hits:
            findings.append(f"{name}: {hits}")

    assert findings == [], f"hardcoded secret patterns found: {findings}"


def test_logs_do_not_emit_env_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = _fake_api_key()
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    writer = RunLogWriter(tmp_path / "runs")
    run_log = RunLog(case_id="case-001", drug="Humira", condition="ra")
    run_log.record_error(f"planner failed with key {secret}")
    run_log.record_decision(
        Decision(
            action=DecisionAction.SUBMIT,
            confidence=0.9,
            rationale="All criteria met for this test case.",
        )
    )
    path = writer.write(run_log)
    content = path.read_text(encoding="utf-8")
    assert secret not in content
    assert "[SECRET]" in content or "All criteria met" in content

    audit = InMemoryAuditTrail()
    from schemas.approval import AuditEventType

    audit.append(
        "case-001",
        AuditEventType.SECURITY_EVENT,
        {"message": f"token={os.environ['ANTHROPIC_API_KEY']}"},
    )
    audit_blob = json.dumps(
        [event.model_dump(mode="json") for event in audit._events],
    )
    assert secret not in audit_blob
