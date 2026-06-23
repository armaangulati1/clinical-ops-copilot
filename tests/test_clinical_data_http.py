"""HTTP transport tests for the clinical-data MCP server."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from agent.config import load_config
from agent.llm import StubPlanner
from agent.mcp_host import StdioMcpHost, qualify_tool
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.decisions import Decision
from schemas.loader import load_case_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, *, attempts: int = 50) -> None:
    for _ in range(attempts):
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    msg = f"clinical-data HTTP server did not become healthy at {base_url}"
    raise RuntimeError(msg)


@dataclass(frozen=True)
class ClinicalDataHttpFixture:
    base_url: str
    mcp_url: str
    token: str
    port: int


@pytest.fixture(scope="module")
def clinical_data_http_server() -> Iterator[ClinicalDataHttpFixture]:
    port = _free_port()
    token = secrets.token_urlsafe(16)
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "CLINICAL_DATA_AUTH_TOKEN": token,
        "EXTRACTOR_BACKEND": "stub",
        "CLINICAL_DATA_CHART_ROOT": str(PROJECT_ROOT / "data" / "charts"),
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "servers.clinical_data",
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_health(base_url)
        yield ClinicalDataHttpFixture(
            base_url=base_url,
            mcp_url=f"{base_url}/mcp",
            token=token,
            port=port,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.clinical_data_http
def test_health_endpoint_returns_ok(
    clinical_data_http_server: ClinicalDataHttpFixture,
) -> None:
    response = httpx.get(f"{clinical_data_http_server.base_url}/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "version" in payload
    assert payload["uptime_seconds"] >= 0


@pytest.mark.clinical_data_http
def test_metrics_endpoint_returns_counters(
    clinical_data_http_server: ClinicalDataHttpFixture,
) -> None:
    response = httpx.get(f"{clinical_data_http_server.base_url}/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "request_count" in payload
    assert "error_count" in payload
    assert "latency_p50_ms" in payload
    assert "latency_p95_ms" in payload


@pytest.mark.clinical_data_http
def test_mcp_endpoint_rejects_missing_or_wrong_token(
    clinical_data_http_server: ClinicalDataHttpFixture,
) -> None:
    missing = httpx.post(
        clinical_data_http_server.mcp_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    wrong = httpx.post(
        clinical_data_http_server.mcp_url,
        headers={"Authorization": "Bearer wrong-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.clinical_data_http
@pytest.mark.anyio
async def test_agent_runs_case_end_to_end_over_streamable_http(
    clinical_data_http_server: ClinicalDataHttpFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_DATA_URL", clinical_data_http_server.mcp_url)
    monkeypatch.setenv("CLINICAL_DATA_AUTH_TOKEN", clinical_data_http_server.token)
    monkeypatch.setenv("EXTRACTOR_BACKEND", "stub")

    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    config = load_config(PROJECT_ROOT)
    assert config.clinical_data_url == clinical_data_http_server.mcp_url

    host = await StdioMcpHost.connect(config)
    writer = RunLogWriter(tmp_path / "runs")
    planner = StubPlanner()

    try:
        result = await run_case(
            case,
            host,
            planner,
            config=config,
            writer=writer,
        )
    finally:
        await host.close()

    decision = Decision.model_validate(result.decision.model_dump(mode="json"))
    assert decision.action in {"submit", "request-more-info", "deny-risk"}
    tools_called = [record.tool for record in result.run_log.tool_calls]
    assert qualify_tool("clinical-data", "extract_chart") in tools_called
    assert qualify_tool("clinical-data", "get_payer_policy") in tools_called


@pytest.mark.deploy
@pytest.mark.network
def test_deployed_health_endpoint_when_configured() -> None:
    deploy_url = os.environ.get("CLINICAL_DATA_DEPLOY_URL", "").strip().rstrip("/")
    if not deploy_url:
        pytest.skip("CLINICAL_DATA_DEPLOY_URL is not set")

    response = httpx.get(f"{deploy_url}/health", timeout=10.0)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
