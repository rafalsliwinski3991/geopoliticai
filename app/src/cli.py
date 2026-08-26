"""Command-line interface for the GeopoliticAI expert agent."""

from __future__ import annotations

import argparse
import asyncio
import sys

from agents.expert import run_pipeline
from config import init_environment, require_env


def main() -> None:
    """Parse CLI arguments and run the pipeline."""
    parser = argparse.ArgumentParser(description="Run GeopoliticAI POC pipeline.")
    parser.add_argument("query", help="Query to analyze")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
        help="Override logging level for this run.",
    )
    args = parser.parse_args()
    init_environment(log_level=args.log_level)
    require_env()
    output = asyncio.run(run_pipeline(args.query))
    data = str(output).encode("utf-8", errors="replace")
    sys.stdout.buffer.write(data + b"\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
