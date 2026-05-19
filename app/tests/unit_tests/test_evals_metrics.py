"""Unit tests for eval scoring functions — no network, no live pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

# evals/ lives outside src/ so it's not on the package path; add it explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.metrics import (  # noqa: E402
    RunSummary,
    aggregate_referee_rates,
    claim_coverage,
    factcheck_accuracy,
    lane_balance,
    referee_correct,
    source_diversity,
)


def test_source_diversity_handles_duplicates() -> None:
    run = RunSummary(
        query_id="t",
        referee_blocked=False,
        citations=[
            "https://www.brookings.edu/a",
            "https://brookings.edu/b",
            "https://www.cfr.org/a",
        ],
    )
    # 2 unique domains over 3 citations
    assert source_diversity(run) == 2 / 3


def test_source_diversity_empty() -> None:
    assert source_diversity(RunSummary(query_id="t", referee_blocked=False)) == 0.0


def test_lane_balance_lower_is_more_balanced() -> None:
    balanced = RunSummary(
        query_id="b",
        referee_blocked=False,
        claims_per_lane={"l": 3, "c": 3, "r": 3, "p": 3},
    )
    skewed = RunSummary(
        query_id="s",
        referee_blocked=False,
        claims_per_lane={"l": 9, "c": 1, "r": 1, "p": 1},
    )
    assert lane_balance(balanced) < lane_balance(skewed)


def test_claim_coverage_substring_hits() -> None:
    run = RunSummary(
        query_id="t",
        referee_blocked=False,
        verdicts={"NATO expanded eastward": "TRUE", "Russia annexed Crimea": "TRUE"},
        expected={"expected_entities": ["NATO", "Crimea", "ASEAN"]},
    )
    # NATO and Crimea hit; ASEAN does not
    assert claim_coverage(run) == 2 / 3


def test_factcheck_accuracy_exact_match() -> None:
    run = RunSummary(
        query_id="t",
        referee_blocked=False,
        verdicts={"a": "TRUE", "b": "FALSE", "c": "MISLEADING"},
    )
    gold = {"a": "TRUE", "b": "FALSE", "c": "TRUE"}
    assert factcheck_accuracy(run, gold) == 2 / 3


def test_referee_correct_truthy() -> None:
    blocked_ok = RunSummary(
        query_id="b",
        referee_blocked=True,
        expected={"referee_blocked": True},
    )
    blocked_bad = RunSummary(
        query_id="b",
        referee_blocked=True,
        expected={"referee_blocked": False},
    )
    assert referee_correct(blocked_ok)
    assert not referee_correct(blocked_bad)


def test_aggregate_referee_rates() -> None:
    runs = [
        # gold-good, pipeline blocked → false positive
        RunSummary(
            query_id="1", referee_blocked=True, expected={"referee_blocked": False}
        ),
        # gold-good, pipeline ok → fine
        RunSummary(
            query_id="2", referee_blocked=False, expected={"referee_blocked": False}
        ),
        # gold-loaded, pipeline blocked → fine
        RunSummary(
            query_id="3", referee_blocked=True, expected={"referee_blocked": True}
        ),
        # gold-loaded, pipeline ok → false negative
        RunSummary(
            query_id="4", referee_blocked=False, expected={"referee_blocked": True}
        ),
    ]
    rates = aggregate_referee_rates(runs)
    assert rates["false_positive_rate"] == 0.5  # 1 of 2 gold-good
    assert rates["false_negative_rate"] == 0.5  # 1 of 2 gold-loaded


def test_aggregate_referee_rates_empty() -> None:
    rates = aggregate_referee_rates([])
    assert rates == {"false_positive_rate": 0.0, "false_negative_rate": 0.0}
