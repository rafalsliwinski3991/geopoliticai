"""Unit tests for `evals.judges.e2e_deep_forecaster`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.e2e_deep_forecaster import (
    VERDICTS_PROMPT,
    _claims_view,
    _faithful_view,
    _tally_view,
    _urls_view,
    _verdicts_view,
    judges,
)
from evals.judges.shared import (
    FAITHFUL_PROMPT,
    build_outcome_judge,
    finished_or_outside,
    skip_unless_finished,
    urls_from_sources,
)


def _failed_output() -> dict[str, Any]:
    return {"finished": False, "side": "ours", "cause": "QuorumError: below quorum"}


def _finished_output() -> dict[str, Any]:
    return {
        "finished": True,
        "side": "",
        "cause": "",
        "answer": (
            "See [one](https://news.example/one).\n"
            "## How the council voted\n"
            "- one member [two](https://news.example/two)"
        ),
        "analysis": "See [one](https://news.example/one).",
        "claims": ["Claim 1: It happens by 2027 (deadline: 2027-12-31)"],
        "verdicts": ["Claim 1: ACCEPTED"],
        "passages": 'Claim 1: It happens by 2027\n- Source 1: "the page\'s text"',
        "source_urls": ["https://news.example/one", "https://news.example/two"],
        "cited_sources": [
            {
                "title": "First",
                "url": "https://news.example/one",
                "text": "first page text",
            }
        ],
        "members_voting": 7,
        "step_seconds": {},
    }


def test_the_six_judges_carry_their_names_kinds_and_views() -> None:
    """The eval's six judges are exactly these, in this order, each with its
    kind and its own view or check — a judge renamed, re-ordered, or wired to
    another's view goes red (review thread)."""
    # Arrange
    from evals.judges.e2e_deep_forecaster import CLAIMS_PROMPT, TALLY_PROMPT

    expected: list[tuple[str, str, Any, bool]] = [
        ("finished_or_outside", "binary", build_outcome_judge().view, False),
        ("urls_from_sources", "binary", _urls_view, True),
        ("faithful_to_sources", "numeric", _faithful_view, True),
        ("claims_checkable", "binary", _claims_view, True),
        ("prose_matches_tally", "binary", _tally_view, True),
        ("verdicts_follow_evidence", "numeric", _verdicts_view, True),
    ]
    prompts = {
        "faithful_to_sources": FAITHFUL_PROMPT,
        "claims_checkable": CLAIMS_PROMPT,
        "prose_matches_tally": TALLY_PROMPT,
        "verdicts_follow_evidence": VERDICTS_PROMPT,
    }
    checks = {
        "finished_or_outside": finished_or_outside,
        "urls_from_sources": urls_from_sources,
    }
    # Act
    built = judges()
    # Assert
    for judge, (name, kind, view, wrapped) in zip(built, expected, strict=True):
        assert judge.name == name
        assert judge.kind == kind
        # A wrapped view keeps its own view under `__wrapped__` (functools.wraps).
        actual = getattr(judge.view, "__wrapped__", judge.view)
        assert actual is view
        assert judge.prompt is prompts.get(judge.name)
        assert judge.check is checks.get(judge.name)


@pytest.mark.parametrize(
    ("output", "outcome_variables"),
    [
        pytest.param(
            _failed_output(),
            {"finished": False, "side": "ours"},
            id="failed",
        ),
        pytest.param({}, None, id="empty dataset output"),
    ],
)
def test_every_answer_judge_skips_a_forecast_that_did_not_finish(
    output: dict[str, Any], outcome_variables: dict[str, Any] | None
) -> None:
    """A view applies only to a forecast that finished: the answer judges skip
    a failed row and the dataset's own empty output, and the outcome judge
    reads a failed row but skips the empty output."""
    # Arrange: `output` comes from the parametrization above.
    answer_views = [
        skip_unless_finished(_urls_view),
        skip_unless_finished(_faithful_view),
        skip_unless_finished(_claims_view),
        skip_unless_finished(_tally_view),
        skip_unless_finished(_verdicts_view),
    ]
    # Act: every answer view declines the output...
    declined = [view({}, output, {}) for view in answer_views]
    # ...and the outcome view reads the failed row, skips the empty output.
    outcome = build_outcome_judge().view({}, output, {})
    # Assert
    assert all(variables is None for variables in declined)
    assert outcome == outcome_variables


def test_the_url_and_faithful_views_read_the_runs_pages() -> None:
    # Arrange
    output = _finished_output()
    # Act
    urls = _urls_view({}, output, {})
    faithful = _faithful_view({}, output, {})
    # Assert: the URL judge reads the run's own source list, never a reference.
    assert urls == {
        "answer": output["answer"],
        "source_urls": ["https://news.example/one", "https://news.example/two"],
    }
    # Assert: faithfulness reads the analysis (not the vote list) and the run's
    # own full cited page text. (Written by hand from the arrange above.)
    assert faithful == {
        "answer": "See [one](https://news.example/one).",
        "sources": ("SOURCE https://news.example/one\nFirst\nfirst page text"),
    }


def test_the_verdicts_view_reads_passages_and_verdicts() -> None:
    # Arrange
    input: dict[str, Any] = {"query": "Forecast if Russia will attack Poland?"}
    output = _finished_output()
    # Act
    variables = _verdicts_view(input, output, {})
    # Assert
    assert variables == {
        "question": "Forecast if Russia will attack Poland?",
        "passages": output["passages"],
        "verdicts": "Claim 1: ACCEPTED",
    }


def test_the_claims_view_reads_the_query_and_the_claims() -> None:
    """Restored from the deleted recorded eval's test: the claims judge reads
    the question it was asked and the claims as one block, by value."""
    # Arrange
    input: dict[str, Any] = {"query": "Forecast if Russia will attack Poland?"}
    output = _finished_output()
    # Act
    variables = _claims_view(input, output, {})
    # Assert
    assert variables == {
        "question": "Forecast if Russia will attack Poland?",
        "claims": "Claim 1: It happens by 2027 (deadline: 2027-12-31)",
    }


def test_the_tally_view_reads_the_verdicts_and_the_answer() -> None:
    """Restored from the deleted recorded eval's test: the tally judge reads
    the counted verdicts and the whole answer, by value."""
    # Arrange
    output = _finished_output()
    # Act
    variables = _tally_view({}, output, {})
    # Assert
    assert variables == {
        "verdicts": "Claim 1: ACCEPTED",
        "answer": output["answer"],
    }


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    from evals.judges.e2e_deep_forecaster import CLAIMS_PROMPT, TALLY_PROMPT

    claims_vars = _claims_view({"query": "q"}, _finished_output(), {})
    tally_vars = _tally_view({}, _finished_output(), {})
    faithful_vars = _faithful_view({}, _finished_output(), {})
    verdicts_vars = _verdicts_view({"query": "q"}, _finished_output(), {})
    assert claims_vars is not None
    assert tally_vars is not None
    assert faithful_vars is not None
    assert verdicts_vars is not None
    # Act + Assert: every field the prompts name is filled by the views.
    assert set(claims_vars) >= {"question", "claims"}
    CLAIMS_PROMPT.format(**claims_vars)
    assert set(tally_vars) >= {"verdicts", "answer"}
    TALLY_PROMPT.format(**tally_vars)
    assert set(faithful_vars) >= {"answer", "sources"}
    FAITHFUL_PROMPT.format(**faithful_vars)
    assert set(verdicts_vars) >= {"question", "passages", "verdicts"}
    VERDICTS_PROMPT.format(**verdicts_vars)
