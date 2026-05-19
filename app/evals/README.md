# Evals

Regression dataset and evaluators for GeopoliticAI. Run before every
deploy. Results land in LangSmith.

## Setup

```bash
cd app
uv sync --extra evals
export LANGCHAIN_TRACING_V2=true
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=geopoliticai-evals
```

## Files

- `dataset.jsonl` — regression queries with expected lane coverage,
  expected referee verdict, and gold-standard supporting URLs.
  Append-only — never delete an entry, mark it `disabled: true` instead.
- `upload_dataset.py` — push `dataset.jsonl` to LangSmith as a versioned
  dataset.
- `run_evals.py` — run the full pipeline against the dataset and emit
  scoring metrics (source diversity, claim coverage, fact-check
  accuracy, referee false-positive/false-negative rate).
- `metrics.py` — pure functions implementing each scorer. Unit-testable.

## What we score

| Metric                         | What it measures                                                            |
| ------------------------------ | --------------------------------------------------------------------------- |
| `source_diversity`             | # unique domains across lanes / total sources (higher = more diverse)       |
| `claim_coverage`               | # claims with ≥1 lane / total expected entities (recall)                    |
| `factcheck_accuracy`           | agreement between pipeline verdicts and gold verdicts                       |
| `referee_false_positive_rate`  | gold-good queries that got blocked                                          |
| `referee_false_negative_rate`  | gold-loaded queries that did NOT get blocked                                |
| `lane_balance`                 | std-dev of per-lane claim counts (lower = more balanced)                    |

## Adding a regression case

Edit `dataset.jsonl` — one JSON object per line:

```json
{
  "id": "ukraine-nato-2024-01",
  "query": "What are the consequences of the Ukraine conflict for NATO?",
  "infosphere": "english",
  "expected": {
    "referee_blocked": false,
    "min_sources_per_lane": 1,
    "must_cite_domains": ["brookings.edu", "cfr.org"],
    "must_not_cite_domains": [],
    "expected_entities": ["NATO", "Ukraine"]
  },
  "tags": ["geopolitics", "alliance"],
  "added": "2026-05-19"
}
```

## Workflow

1. Add the case to `dataset.jsonl`.
2. `uv run python evals/upload_dataset.py` to push to LangSmith.
3. `uv run python evals/run_evals.py` to evaluate the current build.
4. CI gate: PRs must not regress aggregate `factcheck_accuracy` or
   raise `referee_false_positive_rate` above 5%.
