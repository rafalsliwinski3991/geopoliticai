"""Manual live Phoenix quality checks for the expert and orchestrator graphs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

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

from config import REQUIRED_ENV_VARS, init_environment, require_env
from tracing import init_tracing

CASES_PATH = Path(__file__).with_name("cases.json")
CASE_FIELDS = {"agent", "id", "input", "output", "metadata"}
# `"reporter"` is servable from commit 5a: its case data arrives in 5b, but a
# case naming an agent the dispatch table could not route would fail at lookup
# instead of at load.
KNOWN_AGENTS = {"expert", "orchestrator", "reporter"}
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
    """What one case produced, so `main` can decide the exit code once."""

    case_id: str
    scored: int
    judge_errors: int
    failed: list[str]


def load_cases() -> list[dict[str, Any]]:
    """Load the case list and reject accidental schema drift."""
    raw: object = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("cases.json must contain a non-empty list of cases")

    cases = cast(list[dict[str, Any]], raw)
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != CASE_FIELDS:
            raise ValueError(f"each case needs exactly {sorted(CASE_FIELDS)}")
        if case["agent"] not in KNOWN_AGENTS:
            raise ValueError(f"unknown agent: {case['agent']!r}")
        if not isinstance(case["id"], str) or not case["id"].strip():
            raise ValueError("case.id must be a non-empty string")
        if case["id"] in seen:
            raise ValueError(f"duplicate case id: {case['id']}")
        seen.add(case["id"])
        for field in ("input", "output", "metadata"):
            if not isinstance(case[field], dict):
                raise ValueError(f"{case['id']}.{field} must be an object")
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
    beside the other judges instead of erroring the whole kind.

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


def build_expert_evaluators(judge: LLM) -> list[Any]:
    """Build the two expert judges with explicit Phoenix field mappings."""
    groundedness = ClassificationEvaluator(
        name="groundedness",
        llm=judge,
        prompt_template=GROUNDEDNESS_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
        temperature=0,
    )
    usefulness = ClassificationEvaluator(
        name="usefulness",
        llm=judge,
        prompt_template=USEFULNESS_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
        temperature=0,
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
    """Bind one kind's judges, newest mapping first."""
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


@dataclass(frozen=True)
class Kind:
    """One dataset and one experiment: a task, and the judges every case gets.

    Judges belong to the kind and not to the case because Phoenix binds
    evaluators to a dataset, with no way to skip one for a single example.
    A second case added to any kind is therefore graded by exactly this list,
    or it needs a kind of its own.
    """

    task: ExperimentTask
    judges: tuple[str, ...]


def build_kinds() -> dict[str, Kind]:
    """The four kinds, in the order their experiments run."""
    return {
        "expert": Kind(run_expert, ("groundedness", "usefulness")),
        "orchestrator": Kind(run_orchestrator, ("route_correct", "rewrite_quality")),
        # No `route_correct`: `run_report` raises unless the turn paused, and
        # the orchestrator's only `interrupt()` is the reporter subgraph's gate.
        # Pausing therefore implies the destination was `report`, so the judge
        # could only ever score 1.0 or never run at all. The guard is strictly
        # stronger than the judge: it also requires researched material in the
        # thread, which routing alone does not.
        "report": Kind(run_report, ("report_fidelity",)),
        # `route_correct` DOES belong here. `run_e2e` guards only its setup
        # turns; the final turn's routing is ungraded inside the task, so a zero
        # is reachable. See `run_e2e`'s docstring.
        "e2e": Kind(run_e2e, ("route_correct", "rewrite_quality", "usefulness")),
    }


def build_orchestrator_evaluators(judge: LLM) -> list[Any]:
    """Build exact routing plus the LLM rewrite judge."""
    rewrite_quality = ClassificationEvaluator(
        name="rewrite_quality",
        llm=judge,
        prompt_template=REWRITE_QUALITY_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
        temperature=0,
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


def build_reporter_evaluators(judge: LLM) -> list[Any]:
    """Build the single report-fidelity judge with its explicit field mapping."""
    fidelity = ClassificationEvaluator(
        name="report_fidelity",
        llm=judge,
        prompt_template=REPORT_FIDELITY_PROMPT,
        choices=SCORE_CHOICES,
        include_explanation=True,
        temperature=0,
    )
    return [
        bind_evaluator(
            evaluator=fidelity,
            input_mapping={
                "conversation": "input.messages",
                "outline_intent": "reference.outline_intent",
                "report": "output.report",
            },
        ),
    ]


# The per-agent dispatch table: task function, evaluator builder, and the
# evaluation names each agent's case must produce. The loader's
# `KNOWN_AGENTS` must stay a subset of these keys.
def build_agent_run_info() -> dict[
    str, tuple[ExperimentTask, Callable[[LLM], list[Any]], set[str], set[str]]
]:
    return {
        "expert": (
            run_expert,
            build_expert_evaluators,
            {"groundedness", "usefulness"},
            {"groundedness", "usefulness"},
        ),
        "orchestrator": (
            run_orchestrator,
            build_orchestrator_evaluators,
            {"route_correct", "rewrite_quality"},
            {"rewrite_quality"},
        ),
        "reporter": (
            run_report,
            build_reporter_evaluators,
            {"report_fidelity"},
            {"report_fidelity"},
        ),
    }


def validate_evaluations(
    result: RanExperiment,
    *,
    case_id: str,
    expected_names: set[str],
    explanation_names: set[str],
) -> CaseOutcome:
    """Reject structurally invalid results, count judge errors, collect failures."""
    matching = [run for run in result["evaluation_runs"] if run.name in expected_names]
    actual_names = {run.name for run in matching}
    if actual_names != expected_names or len(matching) != len(expected_names):
        raise RuntimeError(
            f"Expected evaluations {sorted(expected_names)}, got {sorted(actual_names)}"
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
            logger.error("%s: %s judge error: %s", case_id, run.name, run.error)
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
        if run.name in explanation_names and (
            not isinstance(explanation, str) or not explanation.strip()
        ):
            raise RuntimeError(f"{run.name} returned no explanation")
        if run.name in JUDGED_EVALUATORS:
            if score < JUDGED_SCORE_THRESHOLD:
                failed.append(f"{run.name}={score}")
        elif not score:
            # A CODE evaluator scores 1.0 when it passes and 0.0 when it fails.
            # Without this branch a `route_correct` of False is recorded as a
            # perfectly valid 0.0 and the run exits green with the routing wrong.
            failed.append(f"{run.name}=failed")
    return CaseOutcome(
        case_id=case_id,
        scored=len(matching) - judge_errors,
        judge_errors=judge_errors,
        failed=failed,
    )


async def run_experiment_case(
    *,
    client: AsyncClient,
    dataset_name: str,
    case_id: str,
    case_count: int,
    example: dict[str, Any],
    task: ExperimentTask,
    evaluators: Sequence[Any],
    expected_names: set[str],
    explanation_names: set[str],
    experiment_name: str,
) -> CaseOutcome:
    """Record one valid graph run and its evaluations for review in Phoenix."""
    dataset = await client.datasets.create_dataset(
        name=dataset_name,
        examples=[example],
        dataset_description="Manual advisory quality smoke case",
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
            "case_count": case_count,
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
    if len(task_runs) != 1 or task_runs[0].get("error"):
        raise RuntimeError(f"Invalid task run: {task_runs}")
    if not isinstance(task_runs[0].get("output"), dict):
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
    return validate_evaluations(
        result,
        case_id=case_id,
        expected_names=expected_names,
        explanation_names=explanation_names,
    )


async def main() -> None:
    """Run every case's checks against live dependencies."""
    cases = load_cases()
    init_environment()
    require_env(
        (*REQUIRED_ENV_VARS, "PHOENIX_COLLECTOR_ENDPOINT", "OPENROUTER_API_KEY")
    )
    if not init_tracing():
        raise RuntimeError("Phoenix tracing could not be initialized")

    # `PHOENIX_API_KEY` is unset locally, where the Compose Phoenix is open, and
    # set from a repository secret in the workflow, where Phoenix Cloud requires
    # it. One client either way: Cloud speaks the same API as the container.
    client = AsyncClient(
        base_url=phoenix_base_url(),
        api_key=os.getenv("PHOENIX_API_KEY") or None,
    )
    # `require_env` above has already rejected an unset or empty value, so the
    # direct read is safe and needs no wrapper of its own.
    judge = LLM(
        provider="openai",
        model=JUDGE_MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    agent_run_info = build_agent_run_info()

    outcomes: list[CaseOutcome] = []
    for case in cases:
        task, build_evaluators, expected_names, explanation_names = agent_run_info[
            case["agent"]
        ]
        # Names are derived from `case["id"]`, not from `case["agent"]`:
        # `create_dataset` with a reused name updates the dataset rather than
        # failing, so agent-keyed cases would pile up as versions of one
        # dataset while their experiments shared a single name.
        outcomes.append(
            await run_experiment_case(
                client=client,
                dataset_name=f"geopoliticai-{case['id']}",
                case_id=case["id"],
                case_count=len(cases),
                example=case,
                task=task,
                evaluators=build_evaluators(judge),
                expected_names=expected_names,
                explanation_names=explanation_names,
                experiment_name=f"{case['id']}-{timestamp}",
            )
        )

    failures = [o for o in outcomes if o.judge_errors or o.failed]
    if failures:
        for outcome in failures:
            logger.error(
                "%s: %d judge errors, failed: %s",
                outcome.case_id,
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
