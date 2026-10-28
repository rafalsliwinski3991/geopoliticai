"""Put several Locust runs side by side as Markdown tables, in seconds.

From `agentic_backend/`: `uv run python -m loadtests.compare results/users-*.json`.
Each file is one run's `--json-file results/users-<N>`, so its name carries
the user count. Locust's final JSON, unlike its CSV, also holds the rounds that
finished during `--stop-timeout`. The load-test workflow appends the output to
the job summary.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from loadtests.turns import FIRST_TOKEN

FILE_PATTERN = re.compile(r"users-(\d+)\.json$")
RUN_HEADER = (
    "| Users | Requests | Failed | Duration s | Req/s |\n"
    "| ---: | ---: | ---: | ---: | ---: |"
)
KIND_HEADER = (
    "| Users | Kind | Requests | Failed | p50 s | p95 s | p99 s | Max s | TTFT p95 s |\n"
    "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
)

Run = tuple[int, list[dict[str, Any]]]


def read_runs(paths: list[str]) -> list[Run]:
    """Load each run's rows with its user count, fewest users first."""
    runs = []
    for path in paths:
        match = FILE_PATTERN.search(path)
        if match is None:
            raise ValueError(f"{path} is not named users-<N>.json")
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        runs.append((int(match.group(1)), rows))
    return sorted(runs, key=lambda run: run[0])


def compute_percentile(response_times: dict[str, int], q: float) -> float:
    """Return the nearest-rank `q`th percentile, in seconds, of Locust's histogram.

    Locust keys each count by its response time in milliseconds, rounded.
    """
    ordered = sorted((float(ms), n) for ms, n in response_times.items())
    rank = max(1, math.ceil(q / 100 * sum(n for _, n in ordered)))
    seen = 0
    for ms, n in ordered:
        seen += n
        if seen >= rank:
            return ms / 1000
    raise ValueError("percentile of no response times")


def format_comparison(runs: list[Run]) -> str:
    """Return one table of whole runs, then one row per run and request kind."""
    lines = ["### Load test", "", RUN_HEADER]
    for users, rows in runs:
        requests = [row for row in rows if row["method"] != FIRST_TOKEN]
        total = sum(row["num_requests"] for row in requests)
        duration = max(row["last_request_timestamp"] for row in requests) - min(
            row["start_time"] for row in requests
        )
        lines.append(
            f"| {users} | {total} | {sum(row['num_failures'] for row in requests)} "
            f"| {duration:.1f} | {total / duration:.1f} |"
        )
    lines += ["", KIND_HEADER]
    for users, rows in runs:
        first_tokens = {
            row["name"]: row["response_times"]
            for row in rows
            if row["method"] == FIRST_TOKEN
        }
        for row in rows:
            if row["method"] == FIRST_TOKEN:
                continue
            times = row["response_times"]
            ttft = first_tokens.get(row["name"])
            lines.append(
                f"| {users} | {row['name']} | {row['num_requests']} "
                f"| {row['num_failures']} | {compute_percentile(times, 50):.3f} "
                f"| {compute_percentile(times, 95):.3f} "
                f"| {compute_percentile(times, 99):.3f} "
                f"| {row['max_response_time'] / 1000:.3f} "
                f"| {'-' if ttft is None else f'{compute_percentile(ttft, 95):.3f}'} |"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Print the comparison of the JSON files named on the command line."""
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        sys.exit("usage: python -m loadtests.compare users-<N>.json ...")
    print(format_comparison(read_runs(paths)))


if __name__ == "__main__":
    main()
