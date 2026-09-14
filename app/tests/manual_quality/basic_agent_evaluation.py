"""Manual live quality checks for the expert and orchestrator graphs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from judge_prompts import (
    GROUNDEDNESS_PROMPT,
    REPORT_FIDELITY_PROMPT,
    REWRITE_QUALITY_PROMPT,
    USEFULNESS_PROMPT,
)
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from phoenix.client import AsyncClient
from phoenix.client.experiments import create_evaluator
from phoenix.client.resources.experiments.types import RanExperiment
from phoenix.evals import LLM, ClassificationEvaluator, bind_evaluator

from config import (
    REQUIRED_ENV_VARS,
    get_arize_platform,
    get_trace_endpoint,
    init_environment,
    require_env,
)
from tracing import init_tracing

CASES_PATH = Path(__file__).with_name("cases.json")
CASE_FIELDS = {"id", "input", "output", "metadata"}
# Pinned, not `openrouter/free`. Phoenix's OpenAI adapter sends the model name
# it was configured with and never reads the resolved model back off the
# response (`phoenix/evals/llm/adapters/openai/adapter.py`), so a router id
# would leave every recorded score attributed to the router and make scores
# uncomparable across runs. On retirement, swap for another free model that
# supports EITHER structured outputs or tool calling: the adapter tries a
# strict `json_schema` first and falls back to tool calling on a
# `BadRequestError` (`phoenix/evals/llm/adapters/openai/adapter.py:149-186`),
# so the viable pool is wider than a `structured_outputs` filter suggests.
JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PHOENIX_TIMEOUT_SECONDS = 180
JUDGE_RETRIES = 3
# Bump when cases, prompts, or the judge change, so runs group per version.
EXPERIMENT_VERSION = "v1"
# Annotated to Phoenix's declared `dict[str, float | int]` choices type:
# an inferred `dict[str, int]` is rejected under `--strict` because `dict`
# is invariant in its value type.
# Two rules, not one number. Phoenix scores a bool evaluator as 0.0 or 1.0, so
# a *passing* CODE evaluator scores 1.0. A single threshold of 3.0 applied
# across both kinds would fail every run, including a perfect one.
JUDGED_SCORE_THRESHOLD = 3.0  # Provisional. No historical scores exist;
# revisit after the first runs.
JUDGED_EVALUATORS = {"groundedness", "usefulness", "rewrite_quality", "report_fidelity"}
SCORE_CHOICES: dict[str, float | int] = {str(score): score for score in range(1, 6)}
DESTINATIONS = {"geopolitical", "other", "report"}

ExperimentTask = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


# CODE evaluators fail on a falsy score, judged evaluators on < 3.0.
logger = logging.getLogger("agent")


@dataclass(frozen=True)
class CaseOutcome:
    """What one group produced, so `main` can decide the exit code once."""

    group_id: str
    scored: int
    judge_errors: int
    failed: list[str]


def load_cases() -> dict[str, list[dict[str, Any]]]:
    """Load the per-group case lists and reject accidental schema drift."""
    raw: object = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("cases.json must contain a non-empty object keyed by group")

    cases = cast(dict[str, list[dict[str, Any]]], raw)
    groups = build_groups()
    specs = judge_specs()
    if set(cases) != set(groups):
        raise ValueError(f"cases.json must hold exactly the groups {sorted(groups)}")

    seen: set[str] = set()
    for group_name, group_cases in cases.items():
        if not isinstance(group_cases, list) or not group_cases:
            raise ValueError(f"{group_name} must hold a non-empty list of cases")
        # Judges belong to the group, so every case under it must carry every
        # reference key those judges read. Without this the run fails deep
        # inside Phoenix's field mapping, per case, after the task has already
        # spent live API credit.
        required: set[str] = set()
        for judge in groups[group_name].judges:
            key = specs[judge].reference_key
            if key is not None:
                required.add(key)
        for case in group_cases:
            if not isinstance(case, dict) or set(case) != CASE_FIELDS:
                raise ValueError(f"each case needs exactly {sorted(CASE_FIELDS)}")
            if not isinstance(case["id"], str) or not case["id"].strip():
                raise ValueError("case.id must be a non-empty string")
            if case["id"] in seen:
                raise ValueError(f"duplicate case id: {case['id']}")
            seen.add(case["id"])
            for field in ("input", "output", "metadata"):
                if not isinstance(case[field], dict):
                    raise ValueError(f"{case['id']}.{field} must be an object")
            missing = sorted(required - set(case["output"]))
            if missing:
                raise ValueError(
                    f"{case['id']} is missing {missing} required by group {group_name}"
                )
    return cases


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


def is_openrouter_success(response: httpx.Response) -> bool:
    """A 200 still fails when OpenRouter relays an upstream error in the body."""
    if response.is_error:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return not (isinstance(body, dict) and "error" in body)


def openrouter_http_clients(
    counts: Counter[str],
) -> tuple[httpx.Client, httpx.AsyncClient]:
    """Clients that count every judge request and every successful reply.

    Requests are counted before sending, so a connection failure with no
    response still shows up as `calls - ok`.
    """

    def on_request(_request: httpx.Request) -> None:
        counts["calls"] += 1

    def on_response(response: httpx.Response) -> None:
        response.read()
        counts["ok"] += is_openrouter_success(response)

    async def on_async_request(_request: httpx.Request) -> None:
        counts["calls"] += 1

    async def on_async_response(response: httpx.Response) -> None:
        await response.aread()
        counts["ok"] += is_openrouter_success(response)

    return (
        httpx.Client(
            timeout=PHOENIX_TIMEOUT_SECONDS,
            event_hooks={"request": [on_request], "response": [on_response]},
        ),
        httpx.AsyncClient(
            timeout=PHOENIX_TIMEOUT_SECONDS,
            event_hooks={
                "request": [on_async_request],
                "response": [on_async_response],
            },
        ),
    )


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
        "standalone_query": query,
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


def thread_output(result: dict[str, Any]) -> dict[str, Any]:
    """Render one finished orchestrator turn into the shared judge fields.

    `conversation` reuses the reporter's own `build_transcript` over
    `messages[:-1]`, so it is the thread as it stood when this turn's answer
    was written, not after. See the comment on the return value.

    Truncation is not a concern here: `MAX_TRANSCRIPT_CHARS` is 400,000 and a
    scripted two-turn thread is a few thousand.

    The import is function-local like every other agent import in this file.
    `agents.reporter.__init__` reaches `graph.py`, whose module scope calls
    `init_tracing()`. At module scope that would fire on import, before `main`
    has loaded the environment, and would drag the whole agent stack into the
    unit tests, which must run with no keys and no database.
    """
    from agents.reporter import build_transcript

    messages = result.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("Turn produced no messages")
    final = messages[-1]
    if not isinstance(final, AIMessage):
        raise RuntimeError("Turn produced no final AI message")
    answer = final.text()
    if not answer.strip():
        raise RuntimeError("Turn produced an empty answer")
    destination = result.get("destination")
    standalone_query = result.get("standalone_query")
    if destination not in DESTINATIONS:
        raise RuntimeError("Turn returned no valid destination")
    if not isinstance(standalone_query, str) or not standalone_query.strip():
        raise RuntimeError("Turn returned no standalone query")
    return {
        "destination": destination,
        "standalone_query": standalone_query,
        "answer": answer,
        # `messages[:-1]`, never the whole list. `final` is this turn's own
        # answer, and both judges that read `conversation` are broken by seeing
        # it. `report_fidelity` asks whether the report stays within the
        # research the conversation supplied, which is vacuous once the report
        # is itself in that conversation. `rewrite_quality` asks whether the
        # rewrite resolves the last user turn, which the answer to that very
        # rewrite gives away. Today's mappings dodge this by reading
        # `input.messages`; trimming keeps the same separation while still
        # showing the judge what the thread actually produced upstream.
        "conversation": build_transcript(messages[:-1]),
    }


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
    return thread_output(result)


async def run_report(input: dict[str, Any]) -> dict[str, Any]:
    """Drive a paused reporter turn to completion over an in-memory saver.

    The module-level `agents.orchestrator.graph.graph` is compiled with no
    checkpointer (`graph.py:59`), and `gate` calls `interrupt()`, so a paused
    run cannot be resumed on it. `build_graph` takes the saver for exactly
    this reason (`orchestrator/graph.py:19-28`).
    """
    from agents.orchestrator.graph import build_graph, build_runtime_config

    graph = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id=f"manual-quality-{uuid4()}")
    records = input.get("messages")
    if not isinstance(records, list) or not records:
        raise ValueError("reporter input.messages must be a non-empty list")
    messages = [message_from_record(record) for record in records]

    result: dict[str, Any] = await graph.ainvoke({"messages": messages}, config=config)
    # Measured against langgraph 1.0.1: resuming a thread with no pending
    # interrupt is a SILENT no-op that returns the completed state and raises
    # nothing. Without this guard, a `classify` misroute or a refusal on
    # `has_researched_material` would let a chat or expert answer flow through
    # every check below — it is still a non-empty `AIMessage` — and be scored
    # by `report_fidelity` as if the reporter had written it. Nothing anywhere
    # would report a problem. Every other task in this file fails loudly on a
    # wrong branch; this is that check.
    if "__interrupt__" not in result:
        raise RuntimeError(
            "Reporter turn never paused: classify did not route to `report`, or "
            "the thread carried no researched material"
        )
    replies = input.get("resume_actions")
    if not isinstance(replies, list) or not replies:
        raise ValueError("reporter input.resume_actions must be a non-empty list")
    for reply in replies:
        result = await graph.ainvoke(Command(resume=reply), config=config)

    return thread_output(result)


async def run_e2e(input: dict[str, Any]) -> dict[str, Any]:
    """Drive a scripted multi-turn conversation over one checkpointed thread.

    Each turn is either a new user message or a resume of a pending pause. The
    module-level orchestrator graph is compiled with no checkpointer, so this
    builds its own exactly as `run_report` does.

    A `query` turn may carry `expect`, the branch it must reach, and this
    raises when it does not. Only *setup* turns carry it. A setup turn exists
    to put a cited expert answer into the thread so that the graded turn has
    something to be a follow-up to; if it lands on the wrong branch the case is
    not testing what it claims to, which is a broken fixture rather than a bad
    answer. `run_report` already draws this line by raising when a turn never
    paused instead of scoring it as a poor report.

    The final turn carries no `expect`. Its routing is the result under test,
    so it stays graded by `route_correct`, where a misroute records a zero
    beside the other judges instead of erroring the whole group.

    A `resume` turn never carries `expect`: resuming does not re-run `classify`.
    """
    from agents.orchestrator.graph import build_graph, build_runtime_config
    from agents.orchestrator.state import build_initial_orchestrator_state

    turns = input.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("e2e input.turns must be a non-empty list")
    # The whole script is checked before the first turn runs, so a typo in an
    # `expect` value costs nothing. Validated after the loop it would surface
    # only once a live search had already been paid for.
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) not in (
            {"query"},
            {"query", "expect"},
            {"resume"},
        ):
            raise ValueError(
                "each e2e turn needs 'query', 'query' with 'expect', or 'resume'"
            )
        if "expect" in turn and turn["expect"] not in DESTINATIONS:
            raise ValueError(f"unknown expected destination: {turn['expect']!r}")

    graph = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id=f"manual-quality-{uuid4()}")
    result: dict[str, Any] = {}
    for turn in turns:
        if "query" in turn:
            # `build_initial_orchestrator_state` is the helper `api.py:318`
            # uses to start a turn. It normalizes whitespace and rejects an
            # empty query, so this task needs no validation of its own.
            result = await graph.ainvoke(
                build_initial_orchestrator_state(turn["query"]), config=config
            )
            expected = turn.get("expect")
            if expected is not None and result.get("destination") != expected:
                raise RuntimeError(
                    f"Setup turn routed to {result.get('destination')!r}, "
                    f"expected {expected!r}. This case is not exercising what "
                    f"it claims to. Query: {turn['query'][:80]}"
                )
            continue
        # Measured against langgraph 1.0.1: resuming a thread with no pending
        # interrupt is a SILENT no-op that returns the completed state and
        # raises nothing. Without this a `classify` misroute would let an
        # expert or chat answer flow through every check below and be scored
        # as if the reporter had written it.
        if "__interrupt__" not in result:
            raise RuntimeError(
                "Resume sent to a thread with no pending interrupt: classify "
                "did not route to `report`, or the thread carried no "
                "researched material"
            )
        result = await graph.ainvoke(Command(resume=turn["resume"]), config=config)
    return thread_output(result)


@create_evaluator(kind="CODE", name="route_correct")
def route_correct(output: Any, reference: dict[str, Any]) -> bool:
    """Require the completed graph to choose the case's expected branch."""
    if not isinstance(output, dict):
        raise RuntimeError("Task produced no output")
    # `bool(...)` because `output.get(...)` is `Any`, and `--strict` rejects
    # returning `Any` from a function declared to return `bool`. Compares the
    # run against its own case's expectation, not against a fixed destination.
    return bool(output.get("destination") == reference["route_correct_destination"])


@dataclass(frozen=True)
class JudgeSpec:
    """How one judge is built, and what a case must supply for it.

    `prompt` is None for `route_correct`, the only CODE evaluator.
    `reference_key` is None for `groundedness`, which reads the run's own
    sources and needs nothing from the case.
    """

    prompt: str | None
    input_mapping: dict[str, str]
    reference_key: str | None


def judge_specs() -> dict[str, JudgeSpec]:
    """Every judge this suite can run, and what each one reads."""
    return {
        "route_correct": JudgeSpec(None, {}, "route_correct_destination"),
        "groundedness": JudgeSpec(
            GROUNDEDNESS_PROMPT,
            {
                "question": "output.standalone_query",
                "answer": "output.answer",
                "sources": "output.sources",
            },
            None,
        ),
        "usefulness": JudgeSpec(
            USEFULNESS_PROMPT,
            {
                "question": "output.standalone_query",
                "answer": "output.answer",
                "requirements": "reference.usefulness_required_points",
            },
            "usefulness_required_points",
        ),
        "rewrite_quality": JudgeSpec(
            REWRITE_QUALITY_PROMPT,
            {
                "history": "output.conversation",
                "rewrite": "output.standalone_query",
                "expected_intent": "reference.rewrite_quality_intent",
            },
            "rewrite_quality_intent",
        ),
        "report_fidelity": JudgeSpec(
            REPORT_FIDELITY_PROMPT,
            {
                "conversation": "output.conversation",
                "outline_intent": "reference.report_fidelity_outline",
                "report": "output.answer",
            },
            "report_fidelity_outline",
        ),
    }


def build_judges(names: Sequence[str], judge: LLM) -> list[Any]:
    """Bind one group's judges, newest mapping first."""
    specs = judge_specs()
    built: list[Any] = []
    for name in names:
        spec = specs[name]
        if spec.prompt is None:
            built.append(route_correct)
            continue
        built.append(
            bind_evaluator(
                evaluator=ClassificationEvaluator(
                    name=name,
                    llm=judge,
                    prompt_template=spec.prompt,
                    choices=SCORE_CHOICES,
                    include_explanation=True,
                    temperature=0,
                ),
                input_mapping=spec.input_mapping,
            )
        )
    return built


def build_ax_judges(names: Sequence[str], judge: LLM) -> list[Any]:
    """Adapt the existing rubric judges to Arize's evaluator interface."""
    from arize.experiments.evaluators.types import EvaluationResult
    from arize.experiments.evaluators.utils import create_evaluator

    phoenix_judges = {
        name: build_judges([name], judge)[0]
        for name in names
        if name != "route_correct"
    }
    built: list[Any] = []
    for name in names:
        if name == "route_correct":

            @create_evaluator(name=name)
            def route_evaluator(
                *, output: Any, dataset_output: Any, **_: object
            ) -> EvaluationResult:
                route_check = cast(Callable[..., bool], route_correct)
                passed = route_check(
                    output=decode_ax_value(output),
                    reference=decode_ax_value(dataset_output),
                )
                return EvaluationResult(
                    score=1.0 if passed else 0.0,
                    label=str(passed),
                    explanation=(
                        "The orchestrator selected the expected destination."
                        if passed
                        else "The orchestrator selected a different destination."
                    ),
                )

            built.append(route_evaluator)
            continue

        phoenix_judge = phoenix_judges[name]

        @create_evaluator(name=name)
        def rubric_evaluator(
            *,
            output: Any,
            input: Any,
            dataset_output: Any,
            bound_judge: Any = phoenix_judge,
            judge_name: str = name,
            **_: object,
        ) -> EvaluationResult:
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
            logger.error("%s judge error: %s", judge_name, last_error)
            return EvaluationResult(
                score=0,
                label="judge_error",
                explanation=f"Judge failed after {JUDGE_RETRIES} attempts.",
            )

        built.append(rubric_evaluator)
    return built


def decode_ax_value(value: Any) -> Any:
    """Decode JSON strings returned for AX's canonical dataset fields."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


@dataclass(frozen=True)
class Group:
    """One dataset and one experiment: a task, and the judges every case gets.

    Judges belong to the group and not to the case because Phoenix binds
    evaluators to a dataset, with no way to skip one for a single example.
    A second case added to any group is therefore graded by exactly this list,
    or it needs a group of its own.
    """

    task: ExperimentTask
    judges: tuple[str, ...]


def build_groups() -> dict[str, Group]:
    """The four groups, in the order their experiments run."""
    return {
        "expert": Group(run_expert, ("groundedness", "usefulness")),
        "orchestrator": Group(run_orchestrator, ("route_correct", "rewrite_quality")),
        # No `route_correct`: `run_report` raises unless the turn paused, and
        # the orchestrator's only `interrupt()` is the reporter subgraph's gate.
        # Pausing therefore implies the destination was `report`, so the judge
        # could only ever score 1.0 or never run at all. The guard is strictly
        # stronger than the judge: it also requires researched material in the
        # thread, which routing alone does not.
        "report": Group(run_report, ("report_fidelity",)),
        # `route_correct` DOES belong here. `run_e2e` guards only its setup
        # turns; the final turn's routing is ungraded inside the task, so a zero
        # is reachable. See `run_e2e`'s docstring.
        "e2e": Group(run_e2e, ("route_correct", "rewrite_quality", "usefulness")),
    }


def validate_evaluations(
    result: RanExperiment,
    *,
    group_name: str,
    group_cases: list[dict[str, Any]],
    expected_names: set[str],
) -> CaseOutcome:
    """Reject structurally invalid results, count judge errors, collect failures."""
    matching = [run for run in result["evaluation_runs"] if run.name in expected_names]
    actual_names = {run.name for run in matching}
    # Was `len(matching) != len(expected_names)`, which is true for any group
    # holding more than one case: `matching` spans every case in the group's
    # experiment, so for N cases it legitimately holds N * len(expected_names)
    # entries.
    expected_total = len(group_cases) * len(expected_names)
    if actual_names != expected_names or len(matching) != expected_total:
        raise RuntimeError(
            f"Expected {expected_total} evaluations for {group_name} "
            f"({sorted(expected_names)} over {len(group_cases)} cases), "
            f"got {len(matching)} named {sorted(actual_names)}"
        )

    judge_errors = 0
    failed: list[str] = []
    for run in matching:
        if run.error:
            # A CODE evaluator's error is a bug in this repository's evaluator
            # and must not be buried in the judge-error tally; only judged
            # evaluators have errors counted.
            if run.name not in JUDGED_EVALUATORS:
                raise RuntimeError(f"{run.name} failed: {run.error}")
            logger.error("%s: %s judge error: %s", group_name, run.name, run.error)
            judge_errors += 1
            continue
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
        # The judges that must return an explanation are exactly the judged
        # ones; no separate `explanation_names` set is threaded through.
        if run.name in JUDGED_EVALUATORS and (
            not isinstance(explanation, str) or not explanation.strip()
        ):
            raise RuntimeError(f"{run.name} returned no explanation")
        if run.name in JUDGED_EVALUATORS:
            if score < JUDGED_SCORE_THRESHOLD:
                failed.append(f"{group_name}/{run.name}={score}")
        elif not score:
            # A CODE evaluator scores 1.0 when it passes and 0.0 when it fails.
            # Without this branch a `route_correct` of False is recorded as a
            # perfectly valid 0.0 and the run exits green with the routing wrong.
            failed.append(f"{group_name}/{run.name}=failed")
    return CaseOutcome(
        group_id=group_name,
        scored=len(matching) - judge_errors,
        judge_errors=judge_errors,
        failed=failed,
    )


async def run_group(
    *,
    client: AsyncClient,
    group_name: str,
    group_cases: list[dict[str, Any]],
    task: ExperimentTask,
    evaluators: Sequence[Any],
    expected_names: set[str],
    experiment_name: str,
) -> CaseOutcome:
    """Record one valid graph run per case and its evaluations in Phoenix."""
    dataset = await client.datasets.create_dataset(
        name=f"geopoliticai-{group_name}",
        # Phoenix reads only input, output and metadata from an example. `id`
        # is this runner's own and stays out of the payload.
        examples=[
            {field: case[field] for field in ("input", "output", "metadata")}
            for case in group_cases
        ],
        dataset_description="Manual advisory quality smoke cases",
        timeout=PHOENIX_TIMEOUT_SECONDS,
    )
    # `experiment_metadata` records the run's static parameters, not its
    # results: `run_experiment` is called before `evaluate_experiment` and
    # Phoenix exposes no way to mutate an experiment's metadata afterwards.
    # It is a parameter of `run_experiment`, not of `create_dataset`.
    task_result = await client.experiments.run_experiment(
        dataset=dataset,
        task=task,
        evaluators=None,
        experiment_name=experiment_name,
        experiment_metadata={
            "judge_model": JUDGE_MODEL,
            "case_count": len(group_cases),
            "judged_score_threshold": JUDGED_SCORE_THRESHOLD,
        },
        print_summary=False,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
        repetitions=1,
        # Kept at 0 deliberately: a retried *task* run spends real Brave and
        # OpenAI credit. Contrast `evaluate_experiment` below.
        retries=0,
    )

    task_runs = task_result["task_runs"]
    if len(task_runs) != len(group_cases):
        raise RuntimeError(
            f"Expected {len(group_cases)} task runs for {group_name}, got {len(task_runs)}"
        )
    for task_run in task_runs:
        if task_run.get("error"):
            raise RuntimeError(f"Invalid task run: {task_run}")
        if not isinstance(task_run.get("output"), dict):
            raise RuntimeError("Task run produced no structured output")

    # `retries=0` is dropped here, inheriting Phoenix's default of 3: the
    # judge is a free-tier OpenRouter endpoint and an un-retried 429 becomes
    # a recorded judge error indistinguishable from a quality regression.
    result = await client.experiments.evaluate_experiment(
        experiment=task_result,
        evaluators=evaluators,
        print_summary=True,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
    )
    # Failures are reported per group, not per case. Every group holds one
    # case today. An evaluation run carries `experiment_run_id`, not a dataset
    # example id, so naming the individual case inside a multi-case group means
    # joining through `task_runs[*]["dataset_example_id"]`. Add that join when
    # a group actually grows a second case.
    return validate_evaluations(
        result,
        group_name=group_name,
        group_cases=group_cases,
        expected_names=expected_names,
    )


def validate_ax_evaluations(
    result: Any,
    *,
    group_name: str,
    group_cases: list[dict[str, Any]],
    expected_names: set[str],
) -> CaseOutcome:
    """Validate the result dataframe returned by Arize's experiment client."""
    rows = result.to_dict(orient="records")
    if len(rows) != len(group_cases):
        raise RuntimeError(
            f"Expected {len(group_cases)} task runs for {group_name}, got {len(rows)}"
        )

    judge_errors = 0
    failed: list[str] = []
    for row in rows:
        if row.get("error"):
            raise RuntimeError(f"Task run failed for {group_name}: {row['error']}")
        for name in expected_names:
            prefix = f"eval.{name}."
            score = row.get(f"{prefix}score")
            label = row.get(f"{prefix}label")
            explanation = row.get(f"{prefix}explanation")
            if score is None or (isinstance(score, float) and score != score):
                if name == "route_correct":
                    raise RuntimeError(f"{name} failed for {group_name}")
                logger.error("%s: %s judge error", group_name, name)
                judge_errors += 1
                continue
            if name in JUDGED_EVALUATORS and (
                not isinstance(explanation, str) or not explanation.strip()
            ):
                raise RuntimeError(f"{name} returned no explanation")
            if name in JUDGED_EVALUATORS and label == "judge_error":
                judge_errors += 1
                continue
            if name in JUDGED_EVALUATORS:
                if (
                    not isinstance(score, (int, float))
                    or score < JUDGED_SCORE_THRESHOLD
                ):
                    failed.append(f"{group_name}/{name}={score}")
            elif not score:
                failed.append(f"{group_name}/{name}=failed")
            if name in JUDGED_EVALUATORS and (
                not isinstance(label, str) or not label.strip()
            ):
                raise RuntimeError(f"{name} returned no label")
    return CaseOutcome(
        group_id=group_name,
        scored=len(rows) * len(expected_names) - judge_errors,
        judge_errors=judge_errors,
        failed=failed,
    )


async def run_ax_group(
    *,
    client: Any,
    space_id: str,
    group_name: str,
    group_cases: list[dict[str, Any]],
    task: ExperimentTask,
    evaluators: Sequence[Any],
    expected_names: set[str],
    experiment_name: str,
) -> CaseOutcome:
    """Run and upload one group through Arize AX."""

    def sync_task(input: Any) -> dict[str, Any]:
        decoded_input = decode_ax_value(input)
        if not isinstance(decoded_input, dict):
            raise ValueError("AX dataset input must decode to an object")

        async def invoke_task() -> dict[str, Any]:
            return await task(decoded_input)

        return asyncio.run(invoke_task())

    dataset = await asyncio.to_thread(
        client.datasets.create,
        name=f"geopoliticai-{experiment_name}",
        space=space_id,
        examples=[
            {
                "attributes.input.value": case["input"],
                "attributes.output.value": case["output"],
                "attributes.metadata": case["metadata"],
            }
            for case in group_cases
        ],
        force_http=True,
    )
    _, result = await asyncio.to_thread(
        client.experiments.run,
        name=experiment_name,
        dataset=dataset.id,
        space=space_id,
        task=sync_task,
        evaluators=evaluators,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
        metadata={
            "judge_model": JUDGE_MODEL,
            "case_count": str(len(group_cases)),
            "judged_score_threshold": str(JUDGED_SCORE_THRESHOLD),
        },
    )
    return validate_ax_evaluations(
        result,
        group_name=group_name,
        group_cases=group_cases,
        expected_names=expected_names,
    )


async def main() -> None:
    """Run every group's checks against live dependencies."""
    cases = load_cases()
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
        # Only the auth-less local Phoenix is supported, so no API key is sent.
        client = AsyncClient(base_url=base_url)
        space_id = None

    openrouter_counts: Counter[str] = Counter()
    sync_http, async_http = openrouter_http_clients(openrouter_counts)
    judge = LLM(
        provider="openai",
        model=JUDGE_MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
        sync_client_kwargs={"http_client": sync_http},
        async_client_kwargs={"http_client": async_http},
    )
    groups = build_groups()

    outcomes: list[CaseOutcome] = []
    for group_name, group in groups.items():
        if platform == "AX":
            assert space_id is not None
            outcomes.append(
                await run_ax_group(
                    client=client,
                    space_id=space_id,
                    group_name=group_name,
                    group_cases=cases[group_name],
                    task=group.task,
                    evaluators=build_ax_judges(group.judges, judge),
                    expected_names=set(group.judges),
                    experiment_name=f"{group_name}-{EXPERIMENT_VERSION}",
                )
            )
        else:
            outcomes.append(
                await run_group(
                    client=client,
                    group_name=group_name,
                    group_cases=cases[group_name],
                    task=group.task,
                    evaluators=build_judges(group.judges, judge),
                    expected_names=set(group.judges),
                    experiment_name=f"{group_name}-{EXPERIMENT_VERSION}",
                )
            )

    judge_errors = sum(o.judge_errors for o in outcomes)
    judged = sum(
        len(cases[name]) * len(JUDGED_EVALUATORS.intersection(group.judges))
        for name, group in groups.items()
    )
    logger.info(
        "OpenRouter: %d calls, %d ok, %d errors; judges: %d succeeded, %d failed",
        openrouter_counts["calls"],
        openrouter_counts["ok"],
        openrouter_counts["calls"] - openrouter_counts["ok"],
        judged - judge_errors,
        judge_errors,
    )

    failures = [o for o in outcomes if o.judge_errors or o.failed]
    if failures:
        for outcome in failures:
            logger.error(
                "%s: %d judge errors, failed: %s",
                outcome.group_id,
                outcome.judge_errors,
                ", ".join(outcome.failed) or "none",
            )
        raise SystemExit(1)


def cli(argv: Sequence[str] | None = None) -> int:
    """Dispatch the live run or the network-free fixture check."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--validate-cases"]:
        load_cases()
        print("cases.json is valid")
        return 0
    if args:
        print(
            "usage: basic_agent_evaluation.py [--validate-cases]",
            file=sys.stderr,
        )
        return 2
    asyncio.run(main())
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
