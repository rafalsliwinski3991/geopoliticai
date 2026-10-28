import json
from pathlib import Path
from typing import Any

import pytest

from loadtests.compare import compute_percentile, format_comparison, read_runs

START = 1_000.0
END = 1_010.0
# 18 requests at 0.5 s, one at 1.25 s, one at 3 s: the nearest-rank p50 is
# the 10th, the p95 the 19th, and the p99 the 20th.
RESPONSE_TIMES = {"500": 18, "1250": 1, "3000": 1}


def _row(method: str, name: str, *, failures: int = 0) -> dict[str, Any]:
    return {
        "method": method,
        "name": name,
        "num_requests": sum(RESPONSE_TIMES.values()),
        "num_failures": failures,
        "response_times": RESPONSE_TIMES,
        "max_response_time": 3000.4,
        "start_time": START,
        "last_request_timestamp": END,
    }


def _write_run(tmp_path: Path, users: int, rows: list[dict[str, Any]]) -> str:
    path = tmp_path / f"users-{users}.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return str(path)


def test_the_runs_are_read_fewest_users_first(tmp_path: Path) -> None:
    """The workflow globs the result files, so the table must not depend on the
    order the shell lists them in: `users-150` sorts before `users-50`."""
    # Arrange
    paths = [_write_run(tmp_path, users, []) for users in (150, 50, 100)]

    # Act
    runs = read_runs(paths)

    # Assert
    assert [users for users, _ in runs] == [50, 100, 150]


def test_a_result_file_without_its_user_count_is_refused(tmp_path: Path) -> None:
    """The user count lives only in the file name; guessing it would mislabel a
    row of the comparison."""
    # Arrange
    path = tmp_path / "run.json"
    path.write_text("[]", encoding="utf-8")

    # Act + Assert
    with pytest.raises(ValueError, match="users-<N>.json"):
        read_runs([str(path)])


@pytest.mark.parametrize(
    ("q", "expected_seconds"),
    [(50, 0.5), (95, 1.25), (99, 3.0), (100, 3.0)],
    ids=["median", "p95 is the 19th of 20", "p99 is the last", "p100 is the max"],
)
def test_a_percentile_is_the_nearest_rank_of_the_histogram(
    q: float, expected_seconds: float
) -> None:
    """A nearest-rank percentile is a time some request really took, so a p95
    never reads faster than the slowest 5% of requests."""
    # Act
    seconds = compute_percentile(RESPONSE_TIMES, q)

    # Assert
    assert seconds == expected_seconds


def test_a_run_row_counts_requests_but_not_first_token_timings(tmp_path: Path) -> None:
    """Locust tabulates the time-to-first-token timings beside the requests;
    counting them would double the turns and the throughput."""
    # Arrange
    path = _write_run(
        tmp_path,
        50,
        [
            _row("POST", "chat"),
            _row("POST", "research", failures=3),
            _row("TTFT", "research"),
        ],
    )

    # Act
    table = format_comparison(read_runs([path]))

    # Assert
    assert "| 50 | 40 | 3 | 10.0 | 4.0 |" in table.splitlines()


def test_a_kind_row_shows_seconds_and_its_first_token_p95(tmp_path: Path) -> None:
    """Locust records milliseconds; the table reads in seconds, with the turn's
    time to first token on the same line as the turn."""
    # Arrange
    path = _write_run(tmp_path, 100, [_row("POST", "chat"), _row("TTFT", "chat")])

    # Act
    table = format_comparison(read_runs([path]))

    # Assert
    assert (
        "| 100 | chat | 20 | 0 | 0.500 | 1.250 | 3.000 | 3.000 | 1.250 |"
        in table.splitlines()
    )


def test_a_kind_without_answer_tokens_shows_a_dash(tmp_path: Path) -> None:
    """The list and history requests stream no answer, so their time to first
    token is absent rather than zero, which would read as instant."""
    # Arrange
    path = _write_run(tmp_path, 100, [_row("GET", "threads")])

    # Act
    table = format_comparison(read_runs([path]))

    # Assert
    assert (
        "| 100 | threads | 20 | 0 | 0.500 | 1.250 | 3.000 | 3.000 | - |"
        in table.splitlines()
    )
