from pathlib import Path

PREAMBLES = Path(__file__).resolve().parents[2] / "harness_eval" / "preambles"


def test_implement_preamble_covers_the_whole_plan():
    # Arrange
    text = (PREAMBLES / "implement.md").read_text()

    # Act
    needles = ["Unit 01", "pull requests: none", "Never open", "never stops the run"]

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
