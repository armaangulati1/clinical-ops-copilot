"""Entry point for the clinical-data MCP server (stdio or StreamableHTTP)."""

from __future__ import annotations

import argparse

from servers.clinical_data.config import load_config
from servers.clinical_data.http_app import run_http_server
from servers.clinical_data.server import configure, mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="clinical-data MCP server")
    parser.add_argument(
        "--chart-root",
        type=str,
        default=None,
        help="Allowed chart root directory (default: ./data/charts or env)",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Transport: stdio for local dev/tests, http for StreamableHTTP deploy",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="HTTP bind host (http transport only; default from env or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP bind port (http transport only; default from env or 8000)",
    )
    args = parser.parse_args()
    configure(load_config(chart_root=args.chart_root))

    if args.transport == "http":
        run_http_server(host=args.host, port=args.port)
        return

    mcp.run()


if __name__ == "__main__":
    main()
