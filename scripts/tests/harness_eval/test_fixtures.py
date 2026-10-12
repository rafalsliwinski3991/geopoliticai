import json
import re
import subprocess
from pathlib import Path

import pytest
from harness_eval import judge

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "scripts" / "harness_eval" / "fixtures" / "deep_forecaster"
SHA_RE = re.compile(r"[0-9a-f]{40}")
UNITS = [f"{n:02d}" for n in range(1, 10)]
FILE_COUNTS = {"01": 13, "02": 5, "03": 25, "04": 22, "05": 25, "06": 26, "07": 24, "08": 8, "09": 22}


def load_task() -> dict:
    return json.loads((FIXTURE / "task.json").read_text())


def plan_headings() -> list[str]:
    """The plan's unit headings, unit by unit: the stack line, §4.N, then §5.N."""
    lines = (FIXTURE / "plan.md").read_text().splitlines()
    groups = [
        [line for line in lines if re.match(pattern, line)]
        for pattern in (r"### Unit \d\d: ", r"### 4\.\d Unit \d\d: ", r"### 5\.\d Unit \d\d$")
    ]
    return [heading for unit in zip(*groups, strict=True) for heading in unit]


def all_headings() -> list[str]:
    units = load_task()["implement"]["units"]
    return [h for unit in units.values() for h in unit["sections"]]


def test_task_has_nine_units_in_order():
    # Arrange
    task = load_task()

    # Act
    units = task["implement"]["units"]

    # Assert
    assert list(units) == UNITS
    for unit in units.values():
        assert len(unit["ref_start"]) == 40
        assert len(unit["ref_end"]) == 40
        assert len(unit["sections"]) == 3
        assert unit["files"]
    assert {n: len(u["files"]) for n, u in units.items()} == FILE_COUNTS


def test_units_chain_on_main():
    # Arrange
    task = load_task()
    units = list(task["implement"]["units"].values())

    # Act
    starts = [u["ref_start"] for u in units]
    expected = [task["implement"]["start"]] + [u["ref_end"] for u in units[:-1]]

    # Assert
    assert starts == expected


@pytest.mark.parametrize("heading", all_headings())
def test_every_unit_section_parses_whole(heading):
    # Arrange
    plan = (FIXTURE / "plan.md").read_text()

    # Act
    block = judge.section(plan, heading)

    # Assert
    assert block.startswith(heading)
    assert len(block.splitlines()) > 5
    if heading.startswith("### 4.5 Unit 05:"):
        assert "write_analysis" in block


def test_every_unit_section_count_is_twenty_seven():
    # Arrange
    headings = all_headings()

    # Act
    count = len(headings)

    # Assert
    assert count == 27


def test_plan_leg_files_exist():
    # Arrange
    task = load_task()
    names = ["brainstorm.md", "plan.md", task["plan"]["reference"]]

    # Act
    missing = [n for n in names if not (FIXTURE / n).is_file()]

    # Assert
    assert missing == []
    assert (FIXTURE / "plan_v1.md").read_text() != (FIXTURE / "plan.md").read_text()


def test_unit_sections_are_the_plans_unit_headings_in_order():
    # Arrange
    expected = plan_headings()

    # Act
    actual = all_headings()

    # Assert
    assert len(expected) == 27
    assert actual == expected


def test_unit_refs_are_commit_ids_and_paths_are_unique():
    # Arrange
    units = load_task()["implement"]["units"]

    # Act
    refs = [u[key] for u in units.values() for key in ("ref_start", "ref_end")]
    duplicated = [n for n, u in units.items() if len(set(u["files"])) != len(u["files"])]

    # Assert
    assert all(SHA_RE.fullmatch(ref) for ref in refs)
    assert duplicated == []


@pytest.mark.parametrize("unit", UNITS)
def test_allowed_paths_cover_the_reference_diff(unit):
    # Arrange
    spec = load_task()["implement"]["units"][unit]
    diff = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--name-only", spec["ref_start"], spec["ref_end"]],
        capture_output=True, text=True, check=False,
    )
    if diff.returncode:
        pytest.skip("the reference commits are not in this checkout")

    # Act
    uncovered = set(diff.stdout.split()) - set(spec["files"])

    # Assert
    assert uncovered == set()
