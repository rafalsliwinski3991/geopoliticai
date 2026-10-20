"""Unit tests for `evals.judges.e2e_deep_forecaster`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.e2e_deep_forecaster import (
    VERDICTS_PROMPT,
    _claims_view,
    _faithful_view,
    _outcome_view,
    _tally_view,
    _urls_view,
    _verdicts_view,
    finished_or_outside,
    judges,
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
        "unanimous_share": 1.0,
        "step_seconds": {},
    }


def test_judge_names_are_the_six_in_order() -> None:
    # Act
    names = [judge.name for judge in judges()]
    # Assert
    assert names == [
        "finished_or_outside",
        "urls_from_sources",
        "faithful_to_sources",
        "claims_checkable",
        "prose_matches_tally",
        "verdicts_follow_evidence",
    ]


@pytest.mark.parametrize(
    ("variables", "verdict"),
    [
        pytest.param({"finished": True, "side": ""}, True, id="finished"),
        pytest.param({"finished": False, "side": "outside"}, True, id="failed outside"),
        pytest.param({"finished": False, "side": "ours"}, False, id="failed ours"),
    ],
)
def test_finished_or_outside(variables: dict[str, Any], verdict: bool) -> None:
    # Act
    result = finished_or_outside(variables)
    # Assert
    assert result is verdict


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
    # Act + Assert: every view but the outcome view declines the output.
    assert _urls_view({}, output, {}) is None
    assert _faithful_view({}, output, {}) is None
    assert _claims_view({}, output, {}) is None
    assert _tally_view({}, output, {}) is None
    assert _verdicts_view({}, output, {}) is None
    # Act + Assert: the outcome view reads a failed row, skips the empty output.
    outcome = _outcome_view({}, output, {})
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


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    from evals.judges.e2e_deep_forecaster import CLAIMS_PROMPT, TALLY_PROMPT
    from evals.judges.expert import FAITHFUL_PROMPT

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
