"""Every eval dataset is validated against its own judges.

For each dataset file, its judges package must exist with unique judge names,
and using each example's expected output as the actual output must leave every
view unraised, match every LLM prompt's template fields, and pass every code
check. This catches prompt/view drift and a bad recording with no new test code.
"""

from __future__ import annotations

import importlib
import string
from datetime import date
from pathlib import Path

import pytest

from evals.helpers.judge import Judge
from evals.helpers.run import load_examples

DATASETS = sorted((Path(__file__).parents[3] / "evals" / "datasets").glob("*.json"))


def _judges_for(path: Path) -> tuple[Judge, ...]:
    module = importlib.import_module(f"evals.judges.{path.stem}")
    judges: tuple[Judge, ...] = module.judges()
    return judges


@pytest.mark.parametrize("path", DATASETS)
def test_load_examples_accepts_every_dataset(path: Path) -> None:
    # Act + Assert (a ValueError would fail the test)
    load_examples(path)


@pytest.mark.parametrize("path", DATASETS)
def test_judges_have_unique_names(path: Path) -> None:
    # Act
    names = [judge.name for judge in _judges_for(path)]

    # Assert
    assert names
    assert len(names) == len(set(names))


@pytest.mark.parametrize("path", DATASETS)
def test_expected_output_passes_its_own_judges(path: Path) -> None:
    # Arrange + Act + Assert: the expected output must satisfy every judge,
    # so the dataset round-trips through the views and checks unchanged.
    judges = _judges_for(path)
    for example in load_examples(path):
        for judge in judges:
            variables = judge.view(
                dict(example["input"]),
                dict(example["output"]),
                dict(example["output"]),
            )
            if variables is None:
                continue  # not applicable to this example
            if judge.prompt is not None:
                fields = {
                    name
                    for _, name, _, _ in string.Formatter().parse(judge.prompt)
                    if name
                }
                assert set(variables) == fields, judge.name
            else:
                assert judge.check is not None
                assert judge.check(variables), judge.name


@pytest.mark.parametrize("path", DATASETS)
def test_backtest_examples_are_dated_before_they_resolve(path: Path) -> None:
    if path.stem != "forecast_backtest":
        pytest.skip("only the backtest dataset carries as_of and resolves_on")
    examples = load_examples(path)
    for example in examples:
        as_of = date.fromisoformat(example["input"]["as_of"])
        resolves_on = date.fromisoformat(example["input"]["resolves_on"])
        assert as_of < resolves_on
        assert date(2026, 7, 1) <= resolves_on <= date(2026, 9, 30)
