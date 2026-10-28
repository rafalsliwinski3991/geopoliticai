import json
from pathlib import Path
from typing import Any

from loadtests.compare import format_comparison, read_runs


def _kind(name: str, *, count: int, errors: int, ttft: float | None) -> dict[str, Any]:
    return {
        "kind": name,
        "count": count,
        "errors": errors,
        "p50": 0.5,
        "p95": 1.25,
        "p99": 2.0,
        "max": 3.0,
        "first_token_p95": ttft,
        "top_errors": [],
    }


def _run(users: int, kinds: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "users": users,
        "rounds": 3,
        "profile": "realistic",
        "wall_seconds": 10.0,
        "kinds": kinds,
    }


def test_the_runs_are_read_fewest_users_first(tmp_path: Path) -> None:
    """The workflow globs result files, so the table must not depend on the
    order the shell lists them in: `users-150` sorts before `users-50`."""
    # Arrange
    paths = []
    for users in (150, 50, 100):
        path = tmp_path / f"users-{users}.json"
        path.write_text(json.dumps(_run(users, [])), encoding="utf-8")
        paths.append(str(path))

    # Act
    runs = read_runs(paths)

    # Assert
    assert [run["users"] for run in runs] == [50, 100, 150]


def test_a_run_row_sums_its_kinds() -> None:
    """The overview row is what a reader compares across loads: every request
    and every failure of the run, and the throughput over the wall time."""
    # Arrange
    run = _run(
        50,
        [
            _kind("chat", count=150, errors=0, ttft=0.9),
            _kind("research", count=150, errors=3, ttft=1.5),
        ],
    )

    # Act
    table = format_comparison([run])

    # Assert
    assert "| 50 | 300 | 3 | 10.0 | 30.0 |" in table.splitlines()


def test_a_kind_without_answer_tokens_shows_a_dash() -> None:
    """The list and history requests stream no answer, so their time to first
    token is absent rather than zero, which would read as instant."""
    # Arrange
    run = _run(100, [_kind("threads", count=300, errors=0, ttft=None)])

    # Act
    table = format_comparison([run])

    # Assert
    assert (
        "| 100 | threads | 300 | 0 | 0.500 | 1.250 | 2.000 | 3.000 | - |"
        in table.splitlines()
    )
