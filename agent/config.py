"""Agent configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_RUNS_DIR = Path("data/runs")
RUNS_DIR_ENV = "AGENT_RUNS_DIR"
EXTRACTOR_BACKEND_ENV = "EXTRACTOR_BACKEND"
DEFAULT_EXTRACTOR_BACKEND = "real"
ANTHROPIC_MODEL_ENV = "ANTHROPIC_MODEL"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DECISION_TOOL_NAME = "record_prior_auth_decision"

CLINICAL_DATA_SERVER = "clinical-data"
CLINIC_OPS_SERVER = "clinic-ops"
CLINICAL_DATA_URL_ENV = "CLINICAL_DATA_URL"
CLINICAL_DATA_AUTH_TOKEN_ENV = "CLINICAL_DATA_AUTH_TOKEN"


@dataclass(frozen=True)
class AgentConfig:
    """Runtime configuration for the prior-auth agent."""

    project_root: Path
    runs_dir: Path
    extractor_backend: str = DEFAULT_EXTRACTOR_BACKEND
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    clinic_ops_latency_min: str = "0"
    clinic_ops_latency_max: str = "0"
    clinic_ops_failure_rate: str = "0"
    clinical_data_url: str | None = None
    clinical_data_auth_token: str | None = None


def load_config(project_root: Path | None = None) -> AgentConfig:
    root = project_root or Path.cwd()
    runs_raw = os.environ.get(RUNS_DIR_ENV, str(DEFAULT_RUNS_DIR))
    return AgentConfig(
        project_root=root,
        runs_dir=Path(runs_raw),
        extractor_backend=os.environ.get(
            EXTRACTOR_BACKEND_ENV,
            DEFAULT_EXTRACTOR_BACKEND,
        ),
        anthropic_model=os.environ.get(ANTHROPIC_MODEL_ENV, DEFAULT_ANTHROPIC_MODEL),
        clinical_data_url=_optional_env(CLINICAL_DATA_URL_ENV),
        clinical_data_auth_token=_optional_env(CLINICAL_DATA_AUTH_TOKEN_ENV),
    )


def _optional_env(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    return raw or None
