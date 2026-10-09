import json
from pathlib import Path

import pytest
from harness_eval import judge

FIXTURE = Path(__file__).resolve().parents[2] / "harness_eval" / "fixtures" / "deep_forecaster"
UNITS = [f"{n:02d}" for n in range(1, 10)]
FILE_COUNTS = {"01": 13, "02": 5, "03": 25, "04": 20, "05": 25, "06": 26, "07": 24, "08": 8, "09": 22}


def load_task() -> dict:
    return json.loads((FIXTURE / "task.json").read_text())


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
