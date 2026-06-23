"""Entry point for the clinic-ops MCP server (stdio transport)."""

from __future__ import annotations

from servers.clinic_ops.config import load_config
from servers.clinic_ops.server import configure, mcp


def main() -> None:
    configure(load_config())
    mcp.run()


if __name__ == "__main__":
    main()
