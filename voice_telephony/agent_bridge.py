"""Run the EXISTING prior-auth agent for one case, unchanged.

This is the same path the file-in voice prototype and ``python -m agent`` use:
load the case, connect the MCP host, run ``agent.runner.run_case`` with the real
``AnthropicPlanner``, and return its :class:`~schemas.decisions.Decision`. The
telephony layer adds nothing to the reasoning; it only decides which case id to
feed in (from the caller's speech) and how to read the answer back.

Kept deliberately thin and injectable: the webhook accepts any
``Callable[[str], Awaitable[Decision]]`` as its decider, so tests can mock the
agent exactly as the existing agent tests do, while production wires in
:func:`run_agent_decision`.
"""

from __future__ import annotations

from pathlib import Path

from agent.config import load_config
from agent.llm import AnthropicPlanner
from agent.mcp_host import StdioMcpHost
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.decisions import Decision
from schemas.loader import load_case_file


class CaseNotFoundError(RuntimeError):
    """Raised when the spoken/routed case id has no case file on disk."""


async def run_agent_decision(case_id: str, *, project_root: Path) -> Decision:
    """Run the unchanged agent on ``case_id`` and return its decision.

    Raises :class:`CaseNotFoundError` if the routed case does not exist, so the
    webhook can speak a clean "I could not find that case" instead of a 500.
    """
    case_path = project_root / "data" / "cases" / f"{case_id}.json"
    if not case_path.is_file():
        msg = f"No case file for {case_id!r}"
        raise CaseNotFoundError(msg)
    case = load_case_file(case_path)

    config = load_config(project_root)
    writer = RunLogWriter(config.runs_dir)
    host = await StdioMcpHost.connect(config)
    planner = AnthropicPlanner(config.anthropic_model)
    try:
        result = await run_case(case, host, planner, config=config, writer=writer)
    finally:
        await host.close()
    return result.decision
