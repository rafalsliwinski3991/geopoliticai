"""Manual live quality check for the orchestrator graph."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import messages_from_dict, messages_to_dict

from config import (
    REQUIRED_ENV_VARS,
    get_arize_platform,
    get_trace_endpoint,
    init_environment,
    require_env,
)
from tracing import init_tracing

DATASET_PATH = Path(__file__).with_name("dataset.json")
# Both platforms reuse a dataset found by name and never refresh its
# examples: bump this whenever dataset.json changes.
DATASET_NAME = "geopoliticai-orchestrator-v1"
AGENT_NAME = "orchestrator"
# Pinned, not `openrouter/free`; see git history.
JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 180
JUDGE_RETRIES = 3
# One judge name across both platforms: the inline evaluator, the AX
# annotation config, and the Phoenix evaluation all carry it.
EVALUATOR_NAME = "orchestrator_quality"
# CI gate: the run fails when the judge's average score falls below this.
MIN_AVG_SCORE = 4.0
# Annotated to Phoenix's declared `dict[str, float | int]` choices type:
# an inferred `dict[str, int]` is rejected under `--strict` because `dict`
# is invariant in its value type.
SCORE_CHOICES: dict[str, float | int] = {str(score): score for score in range(1, 6)}
ORCHESTRATOR_QUALITY_PROMPT = """
Judge the orchestrator's actual output against the expected output for the
same input. Compare the chosen destination, the standalone query, and the final
answer; wording may differ, meaning and routing may not.

Input:
{input}

Actual output:
{output}

Expected output:
{reference}

Choose exactly one label:
1: wrong destination, or the answer/query misses the user's intent.
2: right destination but the query or answer is materially wrong.
3: right destination, intent loosely preserved, noticeable gaps.
4: matches the expected output with a small loss of nuance.
5: fully matches the expected output in routing, query, and answer.

Give a concise evidence-based explanation. Do not provide private chain-of-thought.
"""
logger = logging.getLogger("agent")


def load_examples() -> list[dict[str, Any]]:
    """Load the orchestrator examples from dataset.json."""
    raw: object = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("dataset.json must contain a list of entries")
    for entry in raw:
        if isinstance(entry, dict) and entry.get("agent_name") == AGENT_NAME:
            data = entry.get("data")
            if not isinstance(data, list) or not data:
                raise ValueError(f"{AGENT_NAME} must hold a non-empty list of examples")
            return [
                {"input": example["input"], "output": example["output"]}
                for example in data
            ]
    raise ValueError(f"dataset.json has no {AGENT_NAME} entry")


def phoenix_base_url() -> str:
    """Derive the REST base URL from the repository's OTLP trace endpoint."""
    endpoint = get_trace_endpoint()
    if not endpoint:
        raise ValueError(
            f"Missing collector endpoint for ARIZE_PLATFORM={get_arize_platform()!r}"
        )
    endpoint = endpoint.rstrip("/")
    suffix = "/v1/traces"
    if not endpoint.endswith(suffix):
        raise RuntimeError("The selected collector endpoint must end with /v1/traces")
    return endpoint[: -len(suffix)]


def decode_ax_value(value: Any) -> Any:
    """Decode JSON strings returned for AX's canonical dataset fields."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


async def run_orchestrator(input: dict[str, Any]) -> dict[str, Any]:
    """Run the real full graph with no checkpointer.

    The import is function-local like every other agent import in this file.
    `agents.orchestrator.graph` reaches `graph.py`, whose module scope calls
    `init_tracing()`. At module scope that would fire on import, before `main`
    has loaded the environment, and would drag the whole agent stack into the
    unit tests, which must run with no keys and no database.
    """
    from agents.orchestrator.graph import build_runtime_config, graph

    result: dict[str, Any] = await graph.ainvoke(
        {"messages": messages_from_dict(input["messages"])},
        config=build_runtime_config(thread_id=f"manual-quality-{uuid4()}"),
    )
    return {
        "messages": messages_to_dict(result["messages"]),
        "destination": result.get("destination"),
        "standalone_query": result.get("standalone_query"),
    }


def build_judge(llm: Any) -> Any:
    """Bind the single general judge to Phoenix's classification evaluator."""
    from phoenix.evals import ClassificationEvaluator

    return ClassificationEvaluator(
        name=EVALUATOR_NAME,
        llm=llm,
        prompt_template=ORCHESTRATOR_QUALITY_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
        temperature=0,
    )


def build_ax_judge(bound_judge: Any) -> Any:
    """Wrap the judge as an AX evaluator that retries, then records a failure."""
    from arize.experiments.evaluators.types import EvaluationResult

    def ax_judge(*, input: Any, output: Any, dataset_output: Any) -> Any:
        eval_input = {
            "input": decode_ax_value(input),
            "output": decode_ax_value(output),
            "reference": decode_ax_value(dataset_output),
        }
        last_error: Exception | None = None
        for _attempt in range(JUDGE_RETRIES):
            try:
                score = bound_judge.evaluate(eval_input)[0]
            except Exception as exc:
                last_error = exc
                continue
            return EvaluationResult(
                score=score.score,
                label=score.label,
                explanation=score.explanation,
            )
        assert last_error is not None
        logger.error("orchestrator_quality judge error: %s", last_error)
        return EvaluationResult(
            score=0,
            label="judge_error",
            explanation=f"Judge failed after {JUDGE_RETRIES} attempts.",
        )

    return ax_judge


def annotate_ax_dataset(
    client: Any, space_id: str | None, dataset_id: str, ax_result: Any
) -> None:
    """Post the inline judge's score/label/reasoning onto the dataset examples.

    The experiment's result rows carry `example_id` and the judge's columns;
    annotating the examples makes the reasoning visible next to the score in
    the dataset's Evaluations panel. Annotations are upserted per example, so
    a later run overwrites the earlier reasoning there.
    """
    from arize.annotation_configs.types import (
        CategoricalAnnotationValueRequest,
        OptimizationDirection,
    )
    from arize.datasets.types import AnnotateRecordInput, AnnotationInput

    score_column = f"eval.{EVALUATOR_NAME}.score"
    label_column = f"eval.{EVALUATOR_NAME}.label"
    explanation_column = f"eval.{EVALUATOR_NAME}.explanation"

    annotations = [
        AnnotateRecordInput(
            record_id=str(row["example_id"]),
            values=[
                # Categorical configs reject an explicit `score`: AX derives
                # it from the label, which already matches SCORE_CHOICES.
                AnnotationInput(
                    name=EVALUATOR_NAME,
                    label=row[label_column],
                    text=row[explanation_column],
                )
            ],
        )
        for row in ax_result.to_dict(orient="records")
        if row.get("example_id") and row.get(score_column) is not None
    ]
    if not annotations:
        raise RuntimeError("The experiment produced no judge scores to annotate.")

    for config in client.annotation_configs.list(
        name=EVALUATOR_NAME, space=space_id
    ).annotation_configs:
        if config.name == EVALUATOR_NAME:
            break
    else:
        client.annotation_configs.create_categorical(
            name=EVALUATOR_NAME,
            space=space_id,
            values=[
                CategoricalAnnotationValueRequest(label=label, score=score)
                for label, score in SCORE_CHOICES.items()
            ],
            optimization_direction=OptimizationDirection.MAXIMIZE,
        )
    client.datasets.annotate_examples(
        dataset=dataset_id,
        space=space_id,
        annotations=annotations,
    )
    logger.info("Annotated %d dataset examples with judge results.", len(annotations))


def ensure_min_avg_score(avg_score: float | None) -> None:
    """Exit non-zero when the judge's average score misses the CI gate."""
    if avg_score is None:
        raise SystemExit(
            f"No judge scores were produced; cannot check MIN_AVG_SCORE={MIN_AVG_SCORE}."
        )
    logger.info(
        "Average %s score: %.2f (minimum %.1f)",
        EVALUATOR_NAME,
        avg_score,
        MIN_AVG_SCORE,
    )
    if avg_score < MIN_AVG_SCORE:
        raise SystemExit(
            f"Average {EVALUATOR_NAME} score {avg_score:.2f} is below "
            f"{MIN_AVG_SCORE}; failing the run."
        )


async def main() -> None:
    """Run the orchestrator over every example and score it with one judge."""
    from phoenix.evals import LLM, bind_evaluator

    examples = load_examples()
    init_environment()
    require_env((*REQUIRED_ENV_VARS, "OPENROUTER_API_KEY"))
    platform = get_arize_platform()
    if platform == "AX":
        require_env(("ARIZE_API_KEY", "ARIZE_SPACE_ID"))
        if not init_tracing():
            raise RuntimeError("Arize AX tracing could not be initialized")
        from arize import ArizeClient

        client: Any = ArizeClient(api_key=os.environ["ARIZE_API_KEY"])
        space_id = os.environ["ARIZE_SPACE_ID"]
    else:
        base_url = phoenix_base_url()
        if not init_tracing():
            raise RuntimeError("Phoenix tracing could not be initialized")
        from phoenix.client import AsyncClient

        # Only the auth-less local Phoenix is supported, so no API key is sent.
        client = AsyncClient(base_url=base_url)
        space_id = None

    judge = LLM(
        provider="openai",
        model=JUDGE_MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment_name = f"{AGENT_NAME}-{timestamp}"

    if platform == "AX":
        from arize.utils.resolve import NotFoundError

        def sync_task(input: Any) -> dict[str, Any]:
            decoded_input = decode_ax_value(input)
            if not isinstance(decoded_input, dict):
                raise ValueError("AX dataset input must decode to an object")

            async def invoke_task() -> dict[str, Any]:
                return await run_orchestrator(decoded_input)

            return asyncio.run(invoke_task())

        ax_judge = build_ax_judge(build_judge(judge))

        try:
            dataset = await asyncio.to_thread(
                client.datasets.get, dataset=DATASET_NAME, space=space_id
            )
        except NotFoundError:
            dataset = await asyncio.to_thread(
                client.datasets.create,
                name=DATASET_NAME,
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
        _, ax_result = await asyncio.to_thread(
            client.experiments.run,
            name=experiment_name,
            dataset=dataset.id,
            space=space_id,
            task=sync_task,
            evaluators={EVALUATOR_NAME: ax_judge},
            concurrency=1,
            timeout=TIMEOUT_SECONDS,
        )
        annotate_ax_dataset(client, space_id, dataset.id, ax_result)
        scores = ax_result[f"eval.{EVALUATOR_NAME}.score"].dropna()
        avg_score: float | None = float(scores.mean()) if not scores.empty else None
        failed_tasks = [
            row["error"]
            for row in ax_result.to_dict(orient="records")
            if row.get("error")
        ]
    else:
        try:
            # Get before create: `create_dataset` upserts by name, and examples
            # sent without ids are appended as new ones, so re-running it every
            # run would grow the dataset by a full copy of the examples each time.
            dataset = await client.datasets.get_dataset(
                dataset=DATASET_NAME, timeout=TIMEOUT_SECONDS
            )
        except ValueError:
            dataset = await client.datasets.create_dataset(
                name=DATASET_NAME,
                examples=examples,
                timeout=TIMEOUT_SECONDS,
            )
        # `run_experiment` forwards its `retries` to the evaluators it runs, so
        # the judge must go in a second call: a failed task must not be
        # re-spent, while the free judge still wants its retries (D1).
        task_result = await client.experiments.run_experiment(
            dataset=dataset,
            task=run_orchestrator,
            evaluators=None,
            experiment_name=experiment_name,
            experiment_metadata={"judge_model": JUDGE_MODEL},
            print_summary=False,
            concurrency=1,
            timeout=TIMEOUT_SECONDS,
            retries=0,
        )
        eval_result = await client.experiments.evaluate_experiment(
            experiment=task_result,
            evaluators=[
                bind_evaluator(
                    evaluator=build_judge(judge),
                    input_mapping={
                        "input": "input",
                        "output": "output",
                        "reference": "reference",
                    },
                )
            ],
            print_summary=True,
            concurrency=1,
            timeout=TIMEOUT_SECONDS,
        )
        for run in eval_result["evaluation_runs"]:
            if run.error:
                logger.error("%s judge error: %s", run.name, run.error)
                continue
            result = run.result or {}
            logger.info(
                "%s score=%s label=%s\njudge reasoning: %s",
                run.name,
                result.get("score"),
                result.get("label"),
                result.get("explanation"),
            )
        judge_scores = [
            result.get("score")
            for run in eval_result["evaluation_runs"]
            if not run.error
            and (result := run.result)
            and result.get("score") is not None
        ]
        avg_score = sum(judge_scores) / len(judge_scores) if judge_scores else None
        failed_tasks = [
            run["error"] for run in task_result["task_runs"] if run.get("error")
        ]

    for error in failed_tasks:
        logger.error("Failed orchestrator task run: %s", error)
    if failed_tasks:
        raise SystemExit(1)
    ensure_min_avg_score(avg_score)


if __name__ == "__main__":
    asyncio.run(main())
