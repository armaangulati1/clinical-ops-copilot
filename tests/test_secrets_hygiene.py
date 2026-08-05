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

Three further bypasses were closed on 2026-07-28, all of the same family as the
2026-07-27 one above: a guard that quietly cannot see something is not a guard.

* The self-exemption was matched on **basename**, so any file anywhere in the
  repo named ``test_secrets_hygiene.py`` was invisible to all four scans. It is
  now a single resolved path: this module and nothing else.
* Binary or non-UTF-8 tracked files were silently ``continue``d, so a key inside
  one passed. They are now scanned as bytes with ``errors="replace"``; a key is
  ASCII, so it survives that decode and gets caught.
* The two headline scans called ``pytest.skip`` when git was unavailable, which
  meant a non-git CI checkout ran a suite where they simply vanished. They now
  fall back to a filesystem walk and still fail on a finding.

The key shapes scanned cover **all three providers this repo authenticates to**
(Anthropic, OpenAI, Twilio), not one. A single-vendor scan reporting "no keys"
is true-but-misleading in a repo that holds three kinds of credential.
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
    scan_for_provider_keys,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("agent", "servers", "schemas", "tests", "ui", "scripts")

# This module holds key-SHAPED control strings on purpose, so it is the one file
# the scans must skip. Matched on resolved path, never on basename: a basename
# skip exempts every file in the repo that happens to share the name, which is
# the 2026-07-18 self-exempting-guard defect in a different costume.
SELF_PATH = Path(__file__).resolve()

# Directories a filesystem fallback must never walk into.
WALK_SKIP_DIRS = {"__pycache__", "node_modules", "synthea", "pgdata", "site-packages"}


def _is_self(path: Path) -> bool:
    try:
        return path.resolve() == SELF_PATH
    except OSError:  # pragma: no cover - unresolvable path
        return False


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
    """Read a file as text, decoding lossily rather than skipping.

    The old version returned ``None`` on any non-UTF-8 file and the callers
    silently moved on, so a key inside a binary or latin-1 file passed every
    scan. API keys are ASCII, so a lossy decode preserves them: replacing the
    undecodable bytes loses nothing the scan cares about and keeps the file in
    scope. Only a genuinely unreadable file (permissions, race) returns None.
    """
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def _walk_repo_files() -> list[Path]:
    """Filesystem fallback for when git is unavailable.

    A check that disappears with its tool is not a check, so the git-backed
    scans degrade to this rather than skipping.
    """
    return [
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file()
        and not any(
            part in WALK_SKIP_DIRS or part.startswith(".") for part in path.parts
        )
    ]


def test_repo_has_no_hardcoded_api_keys() -> None:
    findings: list[str] = []
    for path in _iter_source_files():
        if _is_self(path):
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


def test_all_four_provider_key_shapes_are_detected() -> None:
    """Control for the widened scan: one vendor's shape is not a secrets scan.

    Each specimen is assembled from fragments so this file never contains a
    string that looks like a live credential to anyone grepping the repo.

    The ElevenLabs shape was added with the TTS backend. It uses ``sk_`` with an
    UNDERSCORE, so none of the ``sk-`` OpenAI patterns matched it and the scan
    was blind to it while a live one sat in ``.env``.
    """
    specimens = {
        "anthropic": _real_key_shaped_value(),
        "openai": "".join(("sk-", "proj-", "A" * 24, "_b9")),
        "twilio-account-sid": "".join(("AC", "0123456789abcdef" * 2)),
        "twilio-api-key-sid": "".join(("SK", "0123456789abcdef" * 2)),
        "twilio-auth-token": "".join(
            ("TWILIO_AUTH_TOKEN=", "fedcba9876543210" * 2),
        ),
        "elevenlabs": "".join(("sk", "_", "0123456789abcdef" * 3)),
    }
    for expected, specimen in specimens.items():
        assert expected in scan_for_provider_keys(specimen), expected

    # A second OpenAI shape: the classic 48-character key.
    assert "openai" in scan_for_provider_keys("".join(("sk-", "a1B2" * 12)))

    # Negatives: documentation placeholders and ordinary hashes stay quiet.
    for benign in (
        "ANTHROPIC_API_KEY=<your key>",
        "OPENAI_API_KEY=sk-your-key-here",
        "TWILIO_AUTH_TOKEN=$(openssl rand -hex 32)",
        "ELEVENLABS_API_KEY=your-elevenlabs-key-here",
        "sha256: " + "0123456789abcdef" * 4,
    ):
        assert scan_for_provider_keys(benign) == [], benign


def test_elevenlabs_shape_is_not_covered_by_the_openai_hyphen_patterns() -> None:
    """Control proving the new pattern earns its place.

    Swapping the underscore for a hyphen changes which vendor matches, so a
    passing ``elevenlabs`` result cannot be an accidental OpenAI hit.
    """
    underscore = "".join(("sk", "_", "0123456789abcdef" * 3))
    hyphen = underscore.replace("_", "-", 1)
    assert scan_for_provider_keys(underscore) == ["elevenlabs"]
    assert "elevenlabs" not in scan_for_provider_keys(hyphen)


def test_self_exemption_is_a_resolved_path_not_a_basename(tmp_path: Path) -> None:
    """A basename skip exempts every same-named file in the repo. This one does not."""
    impostor = tmp_path / "test_secrets_hygiene.py"
    impostor.write_text("placeholder", encoding="utf-8")
    assert not _is_self(impostor)
    assert _is_self(Path(__file__))


def test_non_utf8_files_are_scanned_rather_than_skipped(tmp_path: Path) -> None:
    """A key inside a latin-1 or binary file used to pass every scan silently."""
    payload = _real_key_shaped_value().encode("ascii")
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\xff\xfe\x00" + payload + b"\x00\xff")

    text = _text_or_none(binary)
    assert text is not None, "a readable file must never be skipped"
    assert scan_for_provider_keys(text) == ["anthropic"]


def test_no_real_api_key_in_any_tracked_file() -> None:
    """Every tracked file, any path and any extension, is free of a real key.

    Not just ``*.py`` under six directories: a push publishes whatever git
    tracks, so that is the surface this has to cover. All three provider key
    shapes are scanned, not only Anthropic's.
    """
    tracked = _git("ls-files")
    paths = [PROJECT_ROOT / name for name in tracked] if tracked else _walk_repo_files()

    findings: list[str] = []
    scanned = 0
    for path in paths:
        if _is_self(path) or not path.is_file():
            continue
        text = _text_or_none(path)
        if text is None:
            continue
        scanned += 1
        vendors = scan_for_provider_keys(text)
        if vendors:
            # Vendor label and path only. Never the matched key.
            rel = path.relative_to(PROJECT_ROOT)
            findings.append(f"{rel}: {vendors}")

    assert scanned > 100, f"only scanned {scanned} files; the guard looks broken"
    assert findings == [], f"provider API key pattern in scanned files: {findings}"


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
        if _is_self(path) or not path.is_file():
            continue
        text = _text_or_none(path)
        if text is None:
            continue
        vendors = scan_for_provider_keys(text)
        if vendors:
            offenders.append(f"{name}: {vendors}")

    assert offenders == [], (
        "untracked but stageable files contain a real API key pattern; "
        f"gitignore them or remove the key: {offenders}"
    )


def test_no_inline_secret_assignment_in_tracked_python() -> None:
    """Widens the ``*.py`` scan from six directories to every tracked Python file.

    The repo root was previously invisible to this check.
    """
    tracked = _git("ls-files", "*.py")
    paths = (
        [PROJECT_ROOT / name for name in tracked]
        if tracked
        else [p for p in _walk_repo_files() if p.suffix == ".py"]
    )

    findings: list[str] = []
    for path in paths:
        name = str(path.relative_to(PROJECT_ROOT))
        if _is_self(path) or not path.is_file():
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
