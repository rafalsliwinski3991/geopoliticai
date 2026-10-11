from pathlib import Path

PREAMBLES = Path(__file__).resolve().parents[2] / "harness_eval" / "preambles"


def test_implement_preamble_covers_unit_05_only():
    # Arrange
    text = (PREAMBLES / "implement.md").read_text()

    # Act
    needles = ["start from Unit 05", "Implement Unit 05 only", "pull requests: none", "Never open", "never stops the run"]

    # Assert
    for needle in needles:
        assert needle in text
    assert ".env" in text


def test_plan_preamble_still_forbids_implementing():
    # Arrange
    text = (PREAMBLES / "plan.md").read_text()

    # Act
    found = "Do not implement it" in text

    # Assert
    assert found
