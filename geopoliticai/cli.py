"""Command-line interface for the GeopoliticAI pipeline."""

from __future__ import annotations

import argparse

from geopoliticai.config import init_environment, require_env
from geopoliticai.graph import run_pipeline


def main() -> None:
    init_environment()
    require_env()

    parser = argparse.ArgumentParser(description="Run GeopoliticAI POC pipeline.")
    parser.add_argument("query", help="Query to analyze")
    args = parser.parse_args()

    print(run_pipeline(args.query))


if __name__ == "__main__":
    main()
