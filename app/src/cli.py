"""Command-line interface for the GeopoliticAI pipeline."""

from __future__ import annotations

import argparse
import sys

from config import init_environment, require_env
from graph import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GeopoliticAI POC pipeline.")
    parser.add_argument("query", help="Query to analyze")
    parser.add_argument(
        "--infosphere",
        choices=("english", "polish"),
        default="english",
        help="Which infosphere sources to use.",
    )
    parser.add_argument(
        "--report",
        choices=("compact", "full"),
        default="compact",
        help="Output mode: compact summary or full report.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
        help="Override logging level for this run.",
    )
    args = parser.parse_args()

    init_environment(log_level=args.log_level)
    require_env()

    output = run_pipeline(
        args.query,
        infosphere=args.infosphere,
        report_mode=args.report,
    )
    data = str(output).encode("utf-8", errors="replace")
    sys.stdout.buffer.write(data + b"\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
