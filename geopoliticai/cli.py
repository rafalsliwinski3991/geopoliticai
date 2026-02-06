"""Command-line interface for the GeopoliticAI pipeline."""

from __future__ import annotations

import argparse
import sys

from geopoliticai.config import init_environment, require_env
from geopoliticai.graph import run_pipeline


def main() -> None:
    init_environment()
    require_env()

    parser = argparse.ArgumentParser(description="Run GeopoliticAI POC pipeline.")
    parser.add_argument("query", help="Query to analyze")
    args = parser.parse_args()

    output = run_pipeline(args.query)
    data = str(output).encode("utf-8", errors="replace")
    sys.stdout.buffer.write(data + b"\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
