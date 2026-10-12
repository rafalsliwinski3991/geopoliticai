import json
import re
import subprocess
from pathlib import Path

import pytest
from harness_eval import judge

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "scripts" / "harness_eval" / "fixtures" / "deep_forecaster"
SHA_RE = re.compile(r"[0-9a-f]{40}")
UNITS = ["05"]
FILE_COUNTS = {"05": 25}
IMPL_PLAN = "ref_plan_to_impl_leg.md"


def load_task() -> dict:
    return json.loads((FIXTURE / "task.json").read_text())


def plan_headings() -> list[str]:
    """The plan's unit headings, unit by unit: the stack line, §4.N, then §5.N."""
    lines = (FIXTURE / IMPL_PLAN).read_text().splitlines()
    groups = [
        [line for line in lines if re.match(pattern, line)]
        for pattern in (r"### Unit \d\d: ", r"### 4\.\d Unit \d\d: ", r"### 5\.\d Unit \d\d$")
    ]
    return [heading for unit in zip(*groups, strict=True) for heading in unit]


def unit_05_headings() -> list[str]:
    """Unit 05 is the fifth unit of the plan: headings 12 to 14 of the nine units' 27."""
    return plan_headings()[12:15]


def all_headings() -> list[str]:
    units = load_task()["implement"]["units"]
    return [h for unit in units.values() for h in unit["sections"]]


def test_task_has_unit_05_only():
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


def test_the_agent_starts_where_unit_05_starts():
    # Arrange
    task = load_task()

    # Act
    unit = task["implement"]["units"]["05"]

    # Assert
    assert task["implement"]["start"] == unit["ref_start"]


@pytest.mark.parametrize("heading", all_headings())
def test_every_unit_section_parses_whole(heading):
    # Arrange
    plan = (FIXTURE / IMPL_PLAN).read_text()

    # Act
    block = judge.section(plan, heading)

    # Assert
    assert block.startswith(heading)
    assert len(block.splitlines()) > 5
    if heading.startswith("### 4.5 Unit 05:"):
        assert "write_analysis" in block


def test_unit_05_has_three_sections():
    # Arrange
    headings = all_headings()

    # Act
    count = len(headings)

    # Assert
    assert count == 3


def test_plan_leg_files_exist():
    # Arrange
    task = load_task()
    names = ["brainstorm.md", task["implement"]["fixture"], task["plan"]["reference"]]

    # Act
    missing = [n for n in names if not (FIXTURE / n).is_file()]

    # Assert
    assert missing == []
    assert task["implement"]["fixture"] == IMPL_PLAN
    assert task["plan"]["reference"] == "ref_plan_to_plan_leg.md"
    assert (FIXTURE / task["plan"]["reference"]).read_text() != (FIXTURE / IMPL_PLAN).read_text()


def test_unit_sections_are_the_plans_unit_05_headings():
    # Arrange
    expected = unit_05_headings()

    # Act
    actual = all_headings()

    # Assert
    assert len(plan_headings()) == 27
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
