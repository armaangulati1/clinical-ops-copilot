"""Secrets hygiene checks."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.audit import InMemoryAuditTrail
from agent.run_log import RunLog, RunLogWriter
from schemas.decisions import Decision, DecisionAction
from schemas.phi_redaction import scan_for_obvious_secrets_in_source

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("agent", "servers", "schemas", "tests", "ui", "scripts")
SCAN_SKIP_FILES = frozenset({"test_secrets_hygiene.py"})


def _fake_api_key() -> str:
    return "".join(("sk-ant-test-", "secret-value-", "1234567890"))


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return files


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
