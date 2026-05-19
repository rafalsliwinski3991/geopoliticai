"""Run the pipeline against the regression dataset and print metrics.

Usage:
    cd app
    uv run --extra evals python evals/run_evals.py

Hits live OpenAI + Brave Search APIs — costs real money. Don't run in CI
without a budget guard. Intended for pre-deploy verification and
periodic drift detection.
"""

from __future__ import annotations

import json
from pathlib import Path

from geopoliticai.config import init_environment, require_env
from geopoliticai.graph import get_compiled_graph
from geopoliticai.models import build_initial_pipeline_state

from evals.metrics import (
    RunSummary,
    aggregate_referee_rates,
    claim_coverage,
    factcheck_accuracy,
    lane_balance,
    referee_correct,
    source_diversity,
)

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
LANES = ("left", "centrist", "right", "people")


def _load_dataset() -> list[dict]:
    return [
        json.loads(line) for line in DATASET_PATH.read_text().splitlines() if line.strip()
    ]


def _summarize(case: dict, final_state: dict) -> RunSummary:
    claims_per_lane = {
        lane: len(final_state.get(f"{lane}_claims", [])) for lane in LANES
    }
    citations: list[str] = []
    for lane in (*LANES, "fact"):
        for src in final_state.get(f"{lane}_sources", []):
            citations.append(getattr(src, "url", ""))
    verdicts = {
        fc.claim.text: fc.verdict for fc in final_state.get("fact_checks", [])
    }
    report = final_state.get("referee_report")
    blocked = bool(getattr(report, "blocked", False))
    return RunSummary(
        query_id=case["id"],
        referee_blocked=blocked,
        claims_per_lane=claims_per_lane,
        citations=citations,
        verdicts=verdicts,
        expected=case["expected"],
    )


def main() -> None:
    init_environment()
    require_env()

    cases = _load_dataset()
    summaries: list[RunSummary] = []

    for case in cases:
        infosphere = case["infosphere"]
        compiled = get_compiled_graph(infosphere)
        initial = build_initial_pipeline_state(case["query"], language=infosphere)
        config = {
            "configurable": {
                "language": infosphere,
                "infosphere_sources": None,  # graph fills from default
            }
        }
        final_state = compiled.invoke(initial, config=config)
        summary = _summarize(case, final_state)
        summaries.append(summary)
        print(
            f"[{summary.query_id}] blocked={summary.referee_blocked} "
            f"lanes={summary.claims_per_lane} "
            f"diversity={source_diversity(summary):.2f} "
            f"balance={lane_balance(summary):.2f} "
            f"coverage={claim_coverage(summary):.2f} "
            f"factcheck={factcheck_accuracy(summary, {}):.2f} "
            f"referee_correct={referee_correct(summary)}"
        )

    rates = aggregate_referee_rates(summaries)
    print()
    print(f"Aggregate referee FPR: {rates['false_positive_rate']:.2%}")
    print(f"Aggregate referee FNR: {rates['false_negative_rate']:.2%}")


if __name__ == "__main__":
    main()
