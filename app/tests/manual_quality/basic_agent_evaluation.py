"""Manual live Phoenix quality checks for the expert and orchestrator graphs."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from phoenix.client import AsyncClient
from phoenix.client.experiments import create_evaluator
from phoenix.client.resources.experiments.types import RanExperiment
from phoenix.evals import LLM, ClassificationEvaluator, bind_evaluator

from config import REQUIRED_ENV_VARS, init_environment, require_env
from tracing import init_tracing

CASES_PATH = Path(__file__).with_name("cases.json")
CASE_NAMES = {"expert", "orchestrator"}
CASE_FIELDS = {"id", "input", "output", "metadata"}
JUDGE_MODEL = "gpt-4o-mini-2024-07-18"
PHOENIX_TIMEOUT_SECONDS = 180
# Annotated to Phoenix's declared `dict[str, float | int]` choices type:
# an inferred `dict[str, int]` is rejected under `--strict` because `dict`
# is invariant in its value type.
SCORE_CHOICES: dict[str, float | int] = {str(score): score for score in range(1, 6)}

ExperimentTask = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

GROUNDEDNESS_PROMPT = """
Judge how well the answer is grounded in the supplied fetched source text.
Treat the source list as the only evidence. Check that material factual claims
are supported and that each inline URL is the URL of the source supporting it.

Question:
{question}

Answer:
{answer}

Sources:
{sources}

Choose exactly one label:
1: material claims are unsupported/contradicted or citations are mostly missing/wrong.
2: some core support exists, but substantial unsupported content or citation errors remain.
3: the main answer is supported, with one meaningful sourcing or citation weakness.
4: all material claims are supported and linked correctly, with only a minor issue.
5: every factual claim is supported by supplied source text and carries the exact supporting inline URL.

Give a concise evidence-based explanation for the label. Refer only to
observable claims, citations, and source text; do not provide private
chain-of-thought.
"""

USEFULNESS_PROMPT = """
Judge whether the answer directly and clearly resolves the question, using the
listed requirements as a coverage checklist rather than as factual evidence.

Question:
{question}

Answer:
{answer}

Required points:
{requirements}

Choose exactly one label:
1: does not answer the central question or is unusable.
2: answers only one part or contains major irrelevant/confusing material.
3: answers both parts basically but lacks an important causal connection or clear prioritization.
4: clearly and concisely explains the security-policy change and April 2023 accession, with a minor omission.
5: precisely connects the invasion, abandonment of non-alignment, accession process, and April 2023 completion without material omission.

Give a concise evidence-based explanation for the label. Identify covered or
missing requirements; do not provide private chain-of-thought.
"""

REWRITE_QUALITY_PROMPT = """
Judge whether the standalone rewrite faithfully resolves the last user turn
from the conversation history. The expected intent is a semantic target, not
text that must be copied.

Conversation history:
{history}

Standalone rewrite:
{rewrite}

Expected intent:
{expected_intent}

Choose exactly one label:
1: does not resolve Sweden/NATO or changes the user's meaning.
2: mentions Sweden but remains materially ambiguous or asks the wrong question.
3: is self-contained but loosely preserves the comparison or imports an unjustified Finland-specific assumption.
4: clearly asks why Sweden pursued NATO and what happened with accession, with a small loss of nuance.
5: fully resolves Sweden, the post-invasion move from non-alignment, and accession outcome without copying Finland's 2023 date or path.

Give a concise evidence-based explanation for the label. Point to the rewrite's
observable wording; do not provide private chain-of-thought.
"""


def load_cases() -> dict[str, dict[str, Any]]:
    """Load the two Phoenix examples and reject accidental schema drift."""
    raw: object = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != CASE_NAMES:
        raise ValueError("cases.json must contain exactly expert and orchestrator")

    cases = cast(dict[str, dict[str, Any]], raw)
    for name, case in cases.items():
        if not isinstance(case, dict) or set(case) != CASE_FIELDS:
            raise ValueError(f"{name} must contain id, input, output, and metadata")
        if not isinstance(case["id"], str) or not case["id"].strip():
            raise ValueError(f"{name}.id must be a non-empty string")
        for field in ("input", "output", "metadata"):
            if not isinstance(case[field], dict):
                raise ValueError(f"{name}.{field} must be an object")
    return cases


def phoenix_base_url() -> str:
    """Derive the REST base URL from the repository's OTLP trace endpoint."""
    endpoint = os.environ["PHOENIX_COLLECTOR_ENDPOINT"].rstrip("/")
    suffix = "/v1/traces"
    if not endpoint.endswith(suffix):
        raise RuntimeError("PHOENIX_COLLECTOR_ENDPOINT must end with /v1/traces")
    return endpoint[: -len(suffix)]


async def run_expert(input: dict[str, Any]) -> dict[str, Any]:
    """Run the real expert graph and return only JSON-serializable data."""
    from agents.expert.graph import graph
    from agents.expert.state import build_initial_pipeline_state

    query = input.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("expert input.query must be a non-empty string")

    result: dict[str, Any] = await graph.ainvoke(build_initial_pipeline_state(query))
    answer = result.get("answer")
    sources = result.get("sources")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Expert graph returned no answer")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("Expert graph returned no sources")

    return {
        "answer": answer,
        "sources": [
            {"title": source.title, "url": source.url, "text": source.text}
            for source in sources
        ],
    }


def message_from_record(record: object) -> AnyMessage:
    """Convert the deliberately small JSON message schema to LangChain."""
    if not isinstance(record, dict):
        raise ValueError("Each orchestrator message must be an object")
    role = record.get("role")
    content = record.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Each orchestrator message needs non-empty content")
    if role == "user":
        return HumanMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content)
    raise ValueError(f"Unsupported message role: {role!r}")


async def run_orchestrator(input: dict[str, Any]) -> dict[str, Any]:
    """Run the real full graph with explicit history and no checkpointer."""
    from agents.orchestrator.graph import build_runtime_config, graph

    records = input.get("messages")
    if not isinstance(records, list) or not records:
        raise ValueError("orchestrator input.messages must be a non-empty list")
    messages = [message_from_record(record) for record in records]

    result: dict[str, Any] = await graph.ainvoke(
        {"messages": messages},
        config=build_runtime_config(thread_id=f"manual-quality-{uuid4()}"),
    )
    destination = result.get("destination")
    standalone_query = result.get("standalone_query")
    result_messages = result.get("messages")
    if destination not in {"geopolitical", "other"}:
        raise RuntimeError("Orchestrator returned no valid destination")
    if not isinstance(standalone_query, str) or not standalone_query.strip():
        raise RuntimeError("Orchestrator returned no standalone query")
    if not isinstance(result_messages, list) or not result_messages:
        raise RuntimeError("Orchestrator returned no messages")
    final_message = result_messages[-1]
    if not isinstance(final_message, AIMessage):
        raise RuntimeError("Orchestrator returned no final AI message")

    return {
        "destination": destination,
        "standalone_query": standalone_query,
        "answer": final_message.text(),
    }


def build_expert_evaluators(judge: LLM) -> list[Any]:
    """Build the two expert judges with explicit Phoenix field mappings."""
    groundedness = ClassificationEvaluator(
        name="groundedness",
        llm=judge,
        prompt_template=GROUNDEDNESS_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
    )
    usefulness = ClassificationEvaluator(
        name="usefulness",
        llm=judge,
        prompt_template=USEFULNESS_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
    )
    return [
        bind_evaluator(
            evaluator=groundedness,
            input_mapping={
                "question": "input.query",
                "answer": "output.answer",
                "sources": "output.sources",
            },
        ),
        bind_evaluator(
            evaluator=usefulness,
            input_mapping={
                "question": "input.query",
                "answer": "output.answer",
                "requirements": "reference.must_address",
            },
        ),
    ]


@create_evaluator(kind="CODE", name="route_correct")
def route_correct(output: Any, reference: dict[str, Any]) -> bool:
    """Require the completed full graph to choose the geopolitical branch."""
    if not isinstance(output, dict):
        raise RuntimeError("Orchestrator task produced no output")
    # `bool(...)` because `output.get(...)` is `Any`, and `--strict` rejects
    # returning `Any` from a function declared to return `bool`.
    return bool(output.get("destination") == reference["destination"] == "geopolitical")


def build_orchestrator_evaluators(judge: LLM) -> list[Any]:
    """Build exact routing plus the LLM rewrite judge."""
    rewrite_quality = ClassificationEvaluator(
        name="rewrite_quality",
        llm=judge,
        prompt_template=REWRITE_QUALITY_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
    )
    return [
        route_correct,
        bind_evaluator(
            evaluator=rewrite_quality,
            input_mapping={
                "history": "input.messages",
                "rewrite": "output.standalone_query",
                "expected_intent": "reference.standalone_query_intent",
            },
        ),
    ]


def validate_and_print_evaluations(
    result: RanExperiment,
    *,
    experiment_name: str,
    expected_names: set[str],
    explanation_names: set[str],
) -> None:
    """Reject incomplete judge output and print a compact reviewer summary."""
    matching = [run for run in result["evaluation_runs"] if run.name in expected_names]
    actual_names = {run.name for run in matching}
    if actual_names != expected_names or len(matching) != len(expected_names):
        raise RuntimeError(
            f"Expected evaluations {sorted(expected_names)}, got {sorted(actual_names)}"
        )

    print(experiment_name)
    for run in sorted(matching, key=lambda item: item.name):
        if run.error:
            raise RuntimeError(f"{run.name} failed: {run.error}")
        evaluation = run.result
        if not isinstance(evaluation, dict):
            raise RuntimeError(f"{run.name} returned no single evaluation result")
        score = evaluation.get("score")
        label = evaluation.get("label")
        explanation = evaluation.get("explanation")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RuntimeError(f"{run.name} returned no numeric score")
        if not isinstance(label, str) or not label.strip():
            raise RuntimeError(f"{run.name} returned no label")
        if run.name in explanation_names and (
            not isinstance(explanation, str) or not explanation.strip()
        ):
            raise RuntimeError(f"{run.name} returned no explanation")

        print(f"  {run.name}: score={score} label={label}")
        if isinstance(explanation, str) and explanation.strip():
            print(f"  explanation: {explanation.strip()}")


async def run_experiment_case(
    *,
    client: AsyncClient,
    dataset_name: str,
    example: dict[str, Any],
    task: ExperimentTask,
    evaluators: Sequence[Any],
    expected_names: set[str],
    explanation_names: set[str],
    experiment_name: str,
) -> RanExperiment:
    """Record one graph run first, then judge it only if the task succeeded."""
    dataset = await client.datasets.create_dataset(
        name=dataset_name,
        examples=[example],
        dataset_description="Manual advisory quality smoke case",
    )
    task_result = await client.experiments.run_experiment(
        dataset=dataset,
        task=task,
        evaluators=None,
        experiment_name=experiment_name,
        print_summary=False,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
        repetitions=1,
        retries=0,
    )

    task_runs = task_result["task_runs"]
    if len(task_runs) != 1 or task_runs[0].get("error"):
        raise RuntimeError(f"Invalid task run: {task_runs}")
    if not isinstance(task_runs[0].get("output"), dict):
        raise RuntimeError("Task run produced no structured output")

    result = await client.experiments.evaluate_experiment(
        experiment=task_result,
        evaluators=evaluators,
        print_summary=False,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
        retries=0,
    )
    validate_and_print_evaluations(
        result,
        experiment_name=experiment_name,
        expected_names=expected_names,
        explanation_names=explanation_names,
    )
    return result


async def main() -> None:
    """Run the expert and orchestrator checks against live dependencies."""
    cases = load_cases()
    init_environment()
    require_env((*REQUIRED_ENV_VARS, "PHOENIX_COLLECTOR_ENDPOINT"))
    if not init_tracing():
        raise RuntimeError("Phoenix tracing could not be initialized")

    client = AsyncClient(base_url=phoenix_base_url())
    judge = LLM(provider="openai", model=JUDGE_MODEL, temperature=0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    expert_result = await run_experiment_case(
        client=client,
        dataset_name="geopoliticai-expert-smoke-v1",
        example=cases["expert"],
        task=run_expert,
        evaluators=build_expert_evaluators(judge),
        expected_names={"groundedness", "usefulness"},
        explanation_names={"groundedness", "usefulness"},
        experiment_name=f"expert-quality-{timestamp}",
    )
    orchestrator_result = await run_experiment_case(
        client=client,
        dataset_name="geopoliticai-orchestrator-smoke-v1",
        example=cases["orchestrator"],
        task=run_orchestrator,
        evaluators=build_orchestrator_evaluators(judge),
        expected_names={"route_correct", "rewrite_quality"},
        explanation_names={"rewrite_quality"},
        experiment_name=f"orchestrator-quality-{timestamp}",
    )

    print(f"expert experiment: {expert_result['experiment_id']}")
    print(f"orchestrator experiment: {orchestrator_result['experiment_id']}")
    print(
        "Advisory reviewer evidence only; not a gate, trend, comparison, or release claim."
    )


def cli(argv: Sequence[str] | None = None) -> int:
    """Dispatch the live run or the network-free fixture check."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check-cases"]:
        load_cases()
        print("cases.json is valid")
        return 0
    if args:
        print(
            "usage: basic_agent_evaluation.py [--check-cases]",
            file=sys.stderr,
        )
        return 2
    asyncio.run(main())
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
