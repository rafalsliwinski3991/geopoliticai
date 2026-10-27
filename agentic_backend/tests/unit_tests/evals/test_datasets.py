"""Every eval dataset loads, has its script and judges, and checks only keys its judges read.

A typo in an expected key (`destinaton`) would otherwise switch a check off
with no sign, because a key present in `expected` is what gets checked
(brainstorm 2026Oct21 Q2). Prompt fields are checked in each judges test.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from evals.helpers.graph import load_messages, load_sources
from evals.helpers.judge import markdown_link_urls
from evals.helpers.run import DATASETS_DIR, eval_kind, load_examples

DATASETS = sorted(DATASETS_DIR.glob("*.json"))
MAKEFILE = DATASETS_DIR.parents[1] / "Makefile"
WORKFLOW = DATASETS_DIR.parents[2] / ".github" / "workflows" / "evals.yml"


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


@pytest.mark.parametrize("path", DATASETS, ids=lambda path: path.stem)
def test_every_recorded_page_loads(path: Path) -> None:
    """A page missing its title, url, or text would crash the run after it was paid for."""
    # Act + Assert (load_sources raises KeyError on a missing field)
    for example in load_examples(path):
        load_sources(example["input"].get("sources", []))


@pytest.mark.parametrize("path", DATASETS, ids=lambda path: path.stem)
def test_every_expected_answer_links_only_its_cases_pages(path: Path) -> None:
    """A reference answer citing a page the case does not record could never be matched."""
    # Act
    stray = {
        (example["metadata"]["name"], url)
        for example in load_examples(path)
        for url in markdown_link_urls(example["output"].get("answer", ""))
        if url not in {page["url"] for page in example["input"].get("sources", [])}
    }
    # Assert
    assert stray == set()


def test_the_makefile_lists_every_eval_under_its_kind() -> None:
    """`make evals-fixed` and `make evals-live` must run every eval of their kind, and only those."""
    # Arrange
    text = MAKEFILE.read_text(encoding="utf-8")
    listed = {
        kind: re.search(rf"^{kind.upper()}_EVALS = (.*)$", text, re.MULTILINE)
        for kind in ("fixed", "live")
    }
    # Act
    made = {
        kind: set(match.group(1).split()) if match else set()
        for kind, match in listed.items()
    }
    # Assert
    for kind in ("fixed", "live"):
        assert made[kind] == {
            path.stem for path in DATASETS if eval_kind(path.stem) == kind
        }


def test_the_workflow_takes_its_evals_from_the_makefile_lists() -> None:
    """`evals.yml` runs what `FIXED_EVALS` and `LIVE_EVALS` list, so it names no eval itself."""
    # Arrange
    text = WORKFLOW.read_text(encoding="utf-8")
    # Act
    named = [path.stem for path in DATASETS if f"evals.{path.stem}" in text]
    # Assert
    assert "s/^FIXED_EVALS = //p" in text
    assert "s/^LIVE_EVALS = //p" in text
    assert named == []
