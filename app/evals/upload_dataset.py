"""Upload `dataset.jsonl` to LangSmith as a versioned dataset.

Usage:
    cd app
    uv run --extra evals python evals/upload_dataset.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
DATASET_NAME = os.getenv("EVAL_DATASET_NAME", "geopoliticai-regression")
DATASET_DESCRIPTION = (
    "Regression queries for the GeopoliticAI pipeline. See "
    "app/evals/README.md for schema and contribution rules."
)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    if not os.getenv("LANGSMITH_API_KEY"):
        raise SystemExit("Set LANGSMITH_API_KEY before uploading.")

    from langsmith import Client  # local import — optional dependency

    client = Client()
    cases = _load_jsonl(DATASET_PATH)

    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description=DATASET_DESCRIPTION,
    )

    for case in cases:
        client.create_example(
            inputs={"query": case["query"], "infosphere": case["infosphere"]},
            outputs={"expected": case["expected"]},
            metadata={"id": case["id"], "tags": case.get("tags", [])},
            dataset_id=dataset.id,
        )

    print(f"Uploaded {len(cases)} examples to dataset '{DATASET_NAME}'.")


if __name__ == "__main__":
    main()
