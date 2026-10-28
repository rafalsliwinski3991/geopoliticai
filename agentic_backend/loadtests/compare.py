"""Put several runs' `--json-out` files side by side as Markdown tables.

From `agentic_backend/`: `uv run python -m loadtests.compare results/*.json`.
The load-test workflow appends the output to the job summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RUN_HEADER = (
    "| Users | Requests | Failed | Wall s | Req/s |\n"
    "| ---: | ---: | ---: | ---: | ---: |"
)
KIND_HEADER = (
    "| Users | Kind | Requests | Errors | p50 s | p95 s | p99 s | Max s | TTFT p95 s |\n"
    "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
)


def read_runs(paths: list[str]) -> list[dict[str, Any]]:
    """Load each run's JSON, fewest users first."""
    runs = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    return sorted(runs, key=lambda run: run["users"])


def format_comparison(runs: list[dict[str, Any]]) -> str:
    """Return one table of whole runs, then one row per run and request kind."""
    lines = ["### Load test", "", RUN_HEADER]
    for run in runs:
        requests = sum(kind["count"] for kind in run["kinds"])
        failed = sum(kind["errors"] for kind in run["kinds"])
        lines.append(
            f"| {run['users']} | {requests} | {failed} | {run['wall_seconds']:.1f} "
            f"| {requests / run['wall_seconds']:.1f} |"
        )
    lines += ["", KIND_HEADER]
    for run in runs:
        for kind in run["kinds"]:
            ttft = kind["first_token_p95"]
            lines.append(
                f"| {run['users']} | {kind['kind']} | {kind['count']} "
                f"| {kind['errors']} | {kind['p50']:.3f} | {kind['p95']:.3f} "
                f"| {kind['p99']:.3f} | {kind['max']:.3f} "
                f"| {'-' if ttft is None else f'{ttft:.3f}'} |"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Print the comparison of the JSON files named on the command line."""
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        sys.exit("usage: python -m loadtests.compare RESULT.json [RESULT.json ...]")
    print(format_comparison(read_runs(paths)))


if __name__ == "__main__":
    main()
