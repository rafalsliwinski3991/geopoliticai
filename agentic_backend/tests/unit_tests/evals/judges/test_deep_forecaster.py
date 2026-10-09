"""Unit tests for `evals.judges.deep_forecaster`."""

from __future__ import annotations

from typing import Any

from evals.judges.deep_forecaster import _claims_view, _tally_view, judges


def test_judge_names_are_the_four_in_order() -> None:
    # Act
    names = [judge.name for judge in judges()]
    # Assert
    assert names == [
        "urls_from_sources",
        "faithful_to_sources",
        "claims_checkable",
        "prose_matches_tally",
    ]


def test_the_two_reused_judges_are_the_experts_own_objects() -> None:
    # Arrange
    from evals.judges.expert import judges as expert_judges

    # Act
    expert = {judge.name: judge for judge in expert_judges()}
    own = {judge.name: judge for judge in judges()}
    # Assert
    for name in ("urls_from_sources", "faithful_to_sources"):
        assert own[name] == expert[name]


def test_the_claims_view_reads_the_query_and_the_claims() -> None:
    # Arrange
    input: dict[str, Any] = {"query": "q"}
    output: dict[str, Any] = {"claims": ["Claim 1: A (deadline: 2027-12-31)"]}
    # Act
    variables = _claims_view(input, output, {})
    # Assert
    assert variables == {
        "question": "q",
        "claims": "Claim 1: A (deadline: 2027-12-31)",
    }


def test_the_tally_view_reads_the_verdicts_and_the_answer() -> None:
    # Arrange
    output: dict[str, Any] = {
        "verdicts": ["Claim 1: ACCEPTED"],
        "answer": "A.",
    }
    # Act
    variables = _tally_view({}, output, {})
    # Assert
    assert variables == {"verdicts": "Claim 1: ACCEPTED", "answer": "A."}


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    from evals.judges.deep_forecaster import CLAIMS_PROMPT, TALLY_PROMPT

    claims_vars = _claims_view({"query": "q"}, {"claims": ["C"]}, {})
    tally_vars = _tally_view({}, {"verdicts": ["V"], "answer": "A"}, {})
    # Act + Assert: every field the prompts name is filled by the views.
    assert set(claims_vars) >= {"question", "claims"}
    CLAIMS_PROMPT.format(**claims_vars)
    assert set(tally_vars) >= {"verdicts", "answer"}
    TALLY_PROMPT.format(**tally_vars)
