"""Production ASGI entrypoint: ``uvicorn voice_telephony.asgi:app``.

Builds the telephony webhook from environment config and wires in the REAL
agent runner. Importing this module requires the telephony environment
variables (see ``voice_telephony.config``) and will raise
:class:`~voice_telephony.config.ConfigError` at startup if any are missing, so a
misconfigured deploy fails loudly instead of silently accepting forged calls.

Tests never import this module; they build the app via
``voice_telephony.app.create_app`` with a mocked decider.
"""

from __future__ import annotations

import functools
from pathlib import Path

from fastapi import FastAPI

from voice_telephony.agent_bridge import run_agent_decision
from voice_telephony.app import create_app
from voice_telephony.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_app() -> FastAPI:
    """Construct the telephony app from environment config + the real agent."""
    config = load_config()
    decider = functools.partial(run_agent_decision, project_root=PROJECT_ROOT)
    return create_app(config=config, decider=decider)


app = build_app()
