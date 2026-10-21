"""Every eval dataset loads, has its script and judges, and checks only keys its judges read.

A typo in an expected key (`destinaton`) would otherwise switch a check off
with no sign, because a key present in `expected` is what gets checked
(brainstorm 2026Oct21 Q2). Prompt fields are checked in each judges test.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from evals.helpers.graph import load_messages
from evals.helpers.run import DATASETS_DIR, load_examples

DATASETS = sorted(DATASETS_DIR.glob("*.json"))


def _judges_module(path: Path) -> object:
    return importlib.import_module(f"evals.judges.{path.stem}")


@pytest.mark.parametrize("path", DATASETS, ids=lambda path: path.stem)
def test_every_dataset_loads(path: Path) -> None:
    """A dataset the runner would refuse must fail here, before any model call is paid for."""
    # Act + Assert (a ValueError would fail the test)
    load_examples(path)


@pytest.mark.parametrize("path", DATASETS, ids=lambda path: path.stem)
def test_every_dataset_has_its_eval_script_and_uniquely_named_judges(
    path: Path,
) -> None:
    """The script, dataset, and judges share one name; a rename that misses one breaks the run."""
    # Act
    importlib.import_module(f"evals.{path.stem}")
    names = [judge.name for judge in getattr(_judges_module(path), "judges")()]
    # Assert
    assert names
    assert len(names) == len(set(names))


@pytest.mark.parametrize("path", DATASETS, ids=lambda path: path.stem)
def test_every_expected_key_is_one_its_judges_read(path: Path) -> None:
    """A misspelled expected key would silently switch its check off."""
    # Arrange
    known = getattr(_judges_module(path), "EXPECTED_KEYS")
    # Act
    unknown = {
        (example["metadata"]["name"], key)
        for example in load_examples(path)
        for key in example["output"]
        if key not in known
    }
    # Assert
    assert unknown == set()


@pytest.mark.parametrize("path", DATASETS, ids=lambda path: path.stem)
def test_every_conversation_uses_known_roles(path: Path) -> None:
    """A role other than user or assistant would crash the run after it was paid for."""
    # Act + Assert (load_messages raises on an unknown role)
    for example in load_examples(path):
        load_messages(example["input"].get("messages", []))
