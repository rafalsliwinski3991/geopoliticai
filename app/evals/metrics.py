"""Scoring functions for GeopoliticAI regression evals.

Pure functions over a ``RunSummary`` so they can be unit-tested without
LangSmith or the live pipeline. The runner in ``run_evals.py`` collects
the data and feeds it through here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlparse


@dataclass
class RunSummary:
    """What the runner records for one evaluated query."""

    query_id: str
    referee_blocked: bool
    claims_per_lane: dict[str, int] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)  # URLs
    verdicts: dict[str, str] = field(default_factory=dict)  # claim_text -> verdict
    expected: dict[str, object] = field(default_factory=dict)


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def source_diversity(run: RunSummary) -> float:
    """Unique domains / total citations. 0..1 (1 = every cite is unique)."""
    if not run.citations:
        return 0.0
    domains = {_domain(u) for u in run.citations if u}
    return len(domains) / len(run.citations)


def lane_balance(run: RunSummary) -> float:
    """Population std-dev of claims-per-lane. Lower = more balanced."""
    counts = list(run.claims_per_lane.values())
    if not counts:
        return 0.0
    return statistics.pstdev(counts)


def claim_coverage(run: RunSummary) -> float:
    """Fraction of expected_entities mentioned across any lane's claims.

    Approximation only: looks for substring presence in the verdict
    keys (claim texts). Tighten with NER if it matters.
    """
    expected = run.expected.get("expected_entities") or []
    if not expected:
        return 1.0
    haystack = " ".join(run.verdicts.keys()).lower()
    hits = sum(1 for ent in expected if str(ent).lower() in haystack)
    return hits / len(expected)


def factcheck_accuracy(run: RunSummary, gold: dict[str, str]) -> float:
    """Agreement between run verdicts and gold verdicts (by claim text)."""
    if not gold:
        return 1.0
    agree = sum(1 for c, v in gold.items() if run.verdicts.get(c) == v)
    return agree / len(gold)


def referee_correct(run: RunSummary) -> bool:
    """True iff the referee's block decision matches the expected outcome."""
    expected = bool(run.expected.get("referee_blocked", False))
    return run.referee_blocked == expected


def aggregate_referee_rates(runs: Iterable[RunSummary]) -> dict[str, float]:
    """Compute referee false-positive and false-negative rates over a run set."""
    runs_list = list(runs)
    if not runs_list:
        return {"false_positive_rate": 0.0, "false_negative_rate": 0.0}
    fp = sum(
        1 for r in runs_list if r.referee_blocked and not r.expected.get("referee_blocked")
    )
    fn = sum(
        1 for r in runs_list if not r.referee_blocked and r.expected.get("referee_blocked")
    )
    n_negative = sum(1 for r in runs_list if not r.expected.get("referee_blocked"))
    n_positive = sum(1 for r in runs_list if r.expected.get("referee_blocked"))
    return {
        "false_positive_rate": fp / n_negative if n_negative else 0.0,
        "false_negative_rate": fn / n_positive if n_positive else 0.0,
    }
