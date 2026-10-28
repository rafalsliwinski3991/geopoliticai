"""Phoenix: dataset, experiment, evaluation, and result collection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Sequence
from typing import Any

from evals.helpers.judge import (
    JUDGE_ERROR,
    JUDGE_MODEL,
    Judge,
    Results,
    Verdict,
    async_score,
    verdict_from_label,
)
from shared.config import get_trace_endpoint


def base_url() -> str:
    """Derive the REST base URL from the repository's OTLP trace endpoint."""
    endpoint = get_trace_endpoint()
    if not endpoint:
        raise ValueError("Missing collector endpoint: set PHOENIX_COLLECTOR_ENDPOINT")
    endpoint = endpoint.rstrip("/")
    suffix = "/v1/traces"
    if not endpoint.endswith(suffix):
        raise RuntimeError("The selected collector endpoint must end with /v1/traces")
    return endpoint[: -len(suffix)]


def build_evaluator(
    judge: Judge, classifier: Any
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Wrap one judge as an async Phoenix evaluator.

    Retries live in `async_score`: Phoenix's `_run_single_evaluation_async`
    catches an evaluator failure per example and only prints it, so
    `evaluate_experiment` never retries one.
    """

    async def evaluate(*, input: Any, output: Any, reference: Any) -> dict[str, Any]:
        verdict = await async_score(judge, classifier, input, output, reference)
        return {
            "score": verdict.score,
            "label": verdict.label,
            "explanation": verdict.explanation,
        }

    return evaluate


def collect(task_result: Any, eval_result: Any, judges: Sequence[Judge]) -> Results:
    """Turn Phoenix's task and evaluation runs into per-judge verdicts."""
    by_name = {judge.name: judge for judge in judges}
    verdicts: dict[str, list[Verdict]] = {judge.name: [] for judge in judges}
    for run in eval_result["evaluation_runs"]:
        judge = by_name.get(run.name)
        if judge is None:
            continue
        if run.error:
            verdicts[judge.name].append(
                Verdict(JUDGE_ERROR, explanation=str(run.error))
            )
            continue
        result = run.result or {}
        verdicts[judge.name].append(
            verdict_from_label(judge, result.get("label"), result.get("explanation"))
        )
    return Results(
        task_errors=[
            str(run["error"]) for run in task_result["task_runs"] if run.get("error")
        ],
        verdicts=verdicts,
    )


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
    """Get or create the dataset, run the task, then evaluate in a second call."""
    from phoenix.client import AsyncClient

    # No API key: the local Phoenix has no auth, and the VPS Phoenix's nginx
    # Basic Auth header comes from PHOENIX_CLIENT_HEADERS, which the client
    # reads itself (arize-phoenix-client 3.3.0, `utils/config.py:412`).
    client = AsyncClient(base_url=base_url())
    try:
        # Get before create: `create_dataset` upserts by name and appends
        # examples sent without ids.
        dataset = await client.datasets.get_dataset(
            dataset=dataset_name, timeout=timeout
        )
    except ValueError:
        dataset = await client.datasets.create_dataset(
            name=dataset_name, examples=examples, timeout=timeout
        )
    # A failed task must not be re-spent on retry, so judges run in a second call.
    task_result = await client.experiments.run_experiment(
        dataset=dataset,
        task=task,
        evaluators=None,
        experiment_name=experiment_name,
        experiment_metadata={"judge_model": JUDGE_MODEL},
        print_summary=False,
        concurrency=1,
        timeout=timeout,
        retries=0,
    )
    eval_result = await client.experiments.evaluate_experiment(
        experiment=task_result,
        evaluators={
            judge.name: build_evaluator(judge, classifiers.get(judge.name))
            for judge in judges
        },
        print_summary=True,
        concurrency=1,
        timeout=timeout,
    )
    return collect(task_result, eval_result, judges)
