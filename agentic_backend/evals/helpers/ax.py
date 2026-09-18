"""Arize AX: dataset, experiment, dataset annotations, and result collection."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from evals.helpers.judge import Judge, Results, Verdict, score, verdict_from_label

logger = logging.getLogger("agent")


def decode_ax_value(value: Any) -> Any:
    """Decode JSON strings returned for AX's canonical dataset fields."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def build_evaluator(judge: Judge, classifier: Any) -> Callable[..., Any]:
    """Wrap one judge as an AX evaluator."""
    from arize.experiments.evaluators.types import EvaluationResult

    def evaluate(*, input: Any, output: Any, dataset_output: Any) -> Any:
        verdict = score(
            judge,
            classifier,
            decode_ax_value(input),
            decode_ax_value(output),
            decode_ax_value(dataset_output),
        )
        return EvaluationResult(
            score=verdict.score,
            label=verdict.label,
            # AX Flight rejects an all-null explanation column: code-check
            # verdicts and not-applicable rows carry no reasoning, so give
            # every stored result a deterministic text.
            explanation=verdict.explanation or "No explanation recorded.",
        )

    return evaluate


def collect(frame: Any, judges: Sequence[Judge]) -> Results:
    """Turn the experiment frame into per-judge verdicts, one per row."""
    rows: list[dict[str, Any]] = frame.to_dict(orient="records")
    verdicts: dict[str, list[Verdict]] = {}
    for judge in judges:
        label_column = f"eval.{judge.name}.label"
        if not any(label_column in row for row in rows):
            verdicts[judge.name] = []
            continue
        verdicts[judge.name] = [
            verdict_from_label(
                judge, row.get(label_column), row.get(f"eval.{judge.name}.explanation")
            )
            for row in rows
        ]
    return Results(
        task_errors=[str(row["error"]) for row in rows if row.get("error")],
        verdicts=verdicts,
    )


def annotate(
    client: Any, space_id: str, dataset_id: str, frame: Any, judges: Sequence[Judge]
) -> None:
    """Post each judge's label and reasoning onto the dataset examples.

    Annotations are upserted per example, so a later run overwrites the
    reasoning shown in the dataset's Evaluations panel.
    """
    from arize.annotation_configs.types import (
        CategoricalAnnotationValueRequest,
        OptimizationDirection,
    )
    from arize.datasets.types import AnnotateRecordInput, AnnotationInput

    annotations = []
    for row in frame.to_dict(orient="records"):
        # A task run that errored is still judged against a `None` output
        # (arize pairs every example with its run), so skip those rows.
        if not row.get("example_id") or row.get("error"):
            continue
        values = []
        for judge in judges:
            label = row.get(f"eval.{judge.name}.label")
            # Only labels in the categorical config: not_applicable and
            # judge_error would be rejected.
            if not (isinstance(label, str) and label in judge.choices):
                continue
            explanation = row.get(f"eval.{judge.name}.explanation")
            # Categorical configs reject an explicit `score`: AX derives it.
            values.append(
                AnnotationInput(
                    name=judge.name,
                    label=label,
                    text=explanation
                    if isinstance(explanation, str) and explanation
                    else None,
                )
            )
        if values:
            annotations.append(
                AnnotateRecordInput(record_id=str(row["example_id"]), values=values)
            )
    if not annotations:
        logger.warning("No judge labels to annotate on the AX dataset.")
        return
    for judge in judges:
        existing = client.annotation_configs.list(name=judge.name, space=space_id)
        if any(config.name == judge.name for config in existing.annotation_configs):
            continue
        client.annotation_configs.create_categorical(
            name=judge.name,
            space=space_id,
            values=[
                CategoricalAnnotationValueRequest(label=label, score=value)
                for label, value in judge.choices.items()
            ],
            optimization_direction=OptimizationDirection.MAXIMIZE,
        )
    client.datasets.annotate_examples(
        dataset=dataset_id, space=space_id, annotations=annotations
    )
    logger.info("Annotated %d dataset examples with judge results.", len(annotations))


async def run(
    *,
    dataset_name: str,
    experiment_name: str,
    examples: list[dict[str, Any]],
    task: Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]],
    judges: Sequence[Judge],
    classifiers: dict[str, Any],
    timeout: int,
) -> Results:
    """Get or create the dataset, run the experiment, annotate, and collect."""
    from arize import ArizeClient
    from arize.utils.resolve import NotFoundError

    client: Any = ArizeClient(api_key=os.environ["ARIZE_API_KEY"])
    space_id = os.environ["ARIZE_SPACE_ID"]

    def sync_task(input: Any) -> dict[str, Any]:
        decoded = decode_ax_value(input)
        if not isinstance(decoded, dict):
            raise ValueError("AX dataset input must decode to an object")
        return asyncio.run(task(decoded))

    try:
        dataset = await asyncio.to_thread(
            client.datasets.get, dataset=dataset_name, space=space_id
        )
    except NotFoundError:
        dataset = await asyncio.to_thread(
            client.datasets.create,
            name=dataset_name,
            space=space_id,
            examples=[
                {
                    "attributes.input.value": example["input"],
                    "attributes.output.value": example["output"],
                }
                for example in examples
            ],
            force_http=True,
        )
    _, frame = await asyncio.to_thread(
        client.experiments.run,
        name=experiment_name,
        dataset=dataset.id,
        space=space_id,
        task=sync_task,
        evaluators={
            judge.name: build_evaluator(judge, classifiers.get(judge.name))
            for judge in judges
        },
        concurrency=1,
        timeout=timeout,
    )
    annotate(client, space_id, dataset.id, frame, judges)
    return collect(frame, judges)
