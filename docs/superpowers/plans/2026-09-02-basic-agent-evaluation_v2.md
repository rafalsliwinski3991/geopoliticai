# Lean Basic Agent Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unfinished offline pilot with one manually run Python script and one JSON case file that execute the live expert and orchestrator graphs, record Phoenix experiments, and store each LLM judge classification with a concise explanation.

**Architecture:** Reuse `app/src/tracing.py`; it already registers Phoenix and auto-instruments LangChain/LangGraph, so the runner must not launch Phoenix or instrument LangChain again. `cases.json` contains exactly two Phoenix-shaped examples with `input` and expected `output`; `basic_agent_evaluation.py` loads them, runs one graph task per experiment, verifies the task succeeded, then applies the settled evaluators. Phoenix owns live graph output, fetched sources, scores, explanations, and traces.

**Tech Stack:** Python 3.10+, LangGraph, `arize-phoenix-client` 3.x, `arize-phoenix-evals` 3.x, existing OpenInference LangChain instrumentation, OpenAI `gpt-4o-mini-2024-07-18`

**Spec:** `docs/brainstorming/2026Sep02_brainstorm_v1_basic-agent-evaluation.md`, amended by the user's request for one runner plus one JSON input/output file

## Global Constraints

- Create exactly two evaluation artifacts: `app/tests/manual_quality/basic_agent_evaluation.py` and `app/tests/manual_quality/cases.json`.
- Do not create a package marker, helper module, report module, evaluator class hierarchy, or manual-runner unit-test package.
- Keep the existing Phoenix client and eval packages in the development dependency group; do not add the full `arize-phoenix` server package.
- Use the existing Compose Phoenix service. Do not call `phoenix.launch_app()`.
- Use the existing `init_tracing()` boundary. Do not call `LangChainInstrumentor().instrument()` or `phoenix.otel.register()` directly in the runner.
- Record two separate experiments, one repetition and no retries: expert quality and full-orchestrator quality.
- Use `gpt-4o-mini-2024-07-18` with temperature `0` for all three LLM judges.
- Store `groundedness`, `usefulness`, and `rewrite_quality` as 1–5 classifications with a concise evidence-based `explanation`; this explanation is the requested judge rationale, not hidden chain-of-thought.
- Store `route_correct` as an exact code result requiring `geopolitical`.
- A graph, search, fetch, answer-model, judge, or Phoenix failure is invalid and unscored. A completed `other` route is valid evidence with `route_correct=false`.
- Keep the runner manual, outside pytest collection, CI, and runtime images. Scores are advisory reviewer evidence, not a gate, trend, comparison, release claim, or broad quality claim.
- Retain unredacted Phoenix data, including fetched article text, live answers, judge inputs, classifications, and explanations.
- Do not modify `.env` or add new environment knobs.
- Update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together when implementing the replacement.

## Scope

### Create

- `app/tests/manual_quality/cases.json` — the two versioned Phoenix examples; `input` is sent to the graph and `output` is the expected result used by evaluators.
- `app/tests/manual_quality/basic_agent_evaluation.py` — JSON loading, existing tracing initialization, two graph tasks, four evaluators, two Phoenix experiments, invalid-run checks, and console summary.

### Modify

- `app/pyproject.toml` — retain Phoenix dev dependencies, replace the obsolete pilot comment, and remove the `pythonpath=["."]` block that existed only for `app/evals/`.
- `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md` — document the lean runner, command, credentials, advisory status, and raw retention.

### Delete

- All files under `app/evals/`.
- All files under `app/tests/unit_tests/evals/`.
- `docs/evals/2026Sep01_task-spec_finland-nato.md`.
- `docs/plans/2026Sep01_plan_offline-eval-pilot_v1.md`.
- `docs/plans/2026Sep01_plan_offline-eval-pilot_v2.md`.

### Non-goals

- No embedded Phoenix server, trace DataFrame query, span-name filtering, or manual annotation upload.
- No new LangGraph, model, search, tracing, or application code.
- No generated result JSON committed to Git; dynamic outputs belong in Phoenix.
- No calibration suite, pass threshold, repetitions, trend dashboard, CI job, scheduled run, or production sampling.
- No unit tests that mock Phoenix internals. Existing graph tests already cover routing, retrieval, nested invocation, and streaming.

---

## Commit 1: Replace the pilot with the lean manual runner

### Task 1: Remove the obsolete pilot and normalize configuration

**Files:**

- Delete: `app/evals/**`
- Delete: `app/tests/unit_tests/evals/**`
- Delete: the task spec and both old pilot plans listed above
- Modify: `app/pyproject.toml:89-114`

**Interfaces:**

- Preserve: `arize-phoenix-client>=3.3,<4.0`
- Preserve: `arize-phoenix-evals>=3.5.1,<4.0`
- Remove: the `evals` import path and its pytest path shim

- [ ] Delete only the obsolete files listed in Scope.

- [ ] Replace the Phoenix dependency comment with:

```toml
    # Manual live quality runner (`tests/manual_quality/`). These stay in `dev`:
    # Docker installs with `--no-dev` and copies only `src/`, while the runner
    # needs Phoenix client/evals only when invoked explicitly by a reviewer.
    "arize-phoenix-client>=3.3,<4.0",
    "arize-phoenix-evals>=3.5.1,<4.0",
]
```

- [ ] Delete the complete `[tool.pytest.ini_options]` block. The replacement is executed by path and imports the editable `app/src` installation; it does not need `app/` added to pytest's path.

### Task 2: Add the single input/output case file

**File:** Create `app/tests/manual_quality/cases.json`

**Contract:** The top level has exactly `expert` and `orchestrator`. Each value is one Phoenix dataset example with `id`, `input`, `output`, and `metadata`. `output` is reference truth, not the generated agent response.

- [ ] Create the file with this exact initial content:

```json
{
  "expert": {
    "id": "expert-finland-nato-v1",
    "input": {
      "query": "Why did Finland abandon military non-alignment after Russia's full-scale invasion of Ukraine, and why did it become a NATO member in April 2023?"
    },
    "output": {
      "must_address": [
        "How Russia's full-scale invasion changed Finland's security policy",
        "Why Finland's NATO accession completed in April 2023"
      ]
    },
    "metadata": {
      "case": "finland-nato",
      "version": 1
    }
  },
  "orchestrator": {
    "id": "orchestrator-sweden-follow-up-v1",
    "input": {
      "messages": [
        {
          "role": "user",
          "content": "Why did Finland become a NATO member in 2023?"
        },
        {
          "role": "assistant",
          "content": "Finland joined NATO in April 2023 after Russia's full-scale invasion changed its security calculus and all allies ratified its accession."
        },
        {
          "role": "user",
          "content": "What about Sweden?"
        }
      ]
    },
    "output": {
      "destination": "geopolitical",
      "standalone_query_intent": "Why Sweden pursued NATO membership after Russia's full-scale invasion and what happened with its accession"
    },
    "metadata": {
      "case": "sweden-follow-up",
      "version": 1
    }
  }
}
```

- [ ] Verify JSON syntax from `app/`:

```bash
uv run python -m json.tool tests/manual_quality/cases.json >/dev/null
```

Expected: exit 0 and no output.

### Task 3: Add one direct Phoenix experiment script

**File:** Create `app/tests/manual_quality/basic_agent_evaluation.py`

**Verified Phoenix API contract:** Context7's `/arize-ai/phoenix` documentation confirms the async dataset/experiment workflow and `bind_evaluator` mappings over `input`, task `output`, and dataset reference data. The repository's pinned `arize-phoenix-client` 3.3.0 additionally confirms that `reference` is an alias for `expected`, passes both names to evaluators, and returns `task_runs` plus `evaluation_runs`. Use `reference` below because it matches current Phoenix terminology; the JSON field remains `output` because that is Phoenix's dataset-example schema.

**Interfaces:**

- `load_cases() -> dict[str, dict[str, Any]]` reads and minimally validates the sibling JSON.
- `run_expert(input) -> dict[str, Any]` returns `answer` and JSON-serializable `sources`.
- `run_orchestrator(input) -> dict[str, Any]` returns `destination`, `standalone_query`, and final `answer`.
- `build_expert_evaluators(judge)` returns groundedness and usefulness judges.
- `build_orchestrator_evaluators(judge)` returns exact-route and rewrite-quality evaluators.
- `run_experiment_case(...) -> RanExperiment` records the task, rejects a failed run, evaluates it, validates the results, and prints the summary.
- `main() -> None` initializes the existing environment/tracing boundary before importing either graph, then runs the two experiments sequentially.

Use dataset names `geopoliticai-expert-smoke-v1` and `geopoliticai-orchestrator-smoke-v1`. Use experiment names `expert-quality-<UTC timestamp>` and `orchestrator-quality-<UTC timestamp>`.

- [ ] Write the script using the following complete implementation shape. This is intended code, not pseudocode; keep it in one file and do not extract helpers into another module.

```python
"""Manual live Phoenix quality checks for the expert and orchestrator graphs."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from phoenix.client import AsyncClient
from phoenix.client.experiments import create_evaluator
from phoenix.client.resources.experiments.types import RanExperiment
from phoenix.evals import ClassificationEvaluator, LLM, bind_evaluator

from config import REQUIRED_ENV_VARS, init_environment, require_env
from tracing import init_tracing

CASES_PATH = Path(__file__).with_name("cases.json")
CASE_NAMES = {"expert", "orchestrator"}
CASE_FIELDS = {"id", "input", "output", "metadata"}
JUDGE_MODEL = "gpt-4o-mini-2024-07-18"
PHOENIX_TIMEOUT_SECONDS = 180
SCORE_CHOICES = {str(score): score for score in range(1, 6)}

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

    result: dict[str, Any] = await graph.ainvoke(
        build_initial_pipeline_state(query)
    )
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
    return output.get("destination") == reference["destination"] == "geopolitical"


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
    matching = [
        run for run in result["evaluation_runs"] if run.name in expected_names
    ]
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
    print("Advisory reviewer evidence only; not a gate, trend, comparison, or release claim.")


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
```

- [ ] Preserve these important boundaries when adapting the example to satisfy static typing:

  - Graph imports remain local to `run_expert` and `run_orchestrator`, after `init_tracing()`.
  - Do not import `phoenix as px`, call `launch_app`, call `phoenix.otel.register`, or invoke `LangChainInstrumentor`.
  - Do not suppress evaluator tracing; Phoenix should retain the judge calls and explanations with the experiment.
  - Keep the two-stage `run_experiment` then `evaluate_experiment` sequence so task failures are unscored.
  - Do not catch graph, judge, or Phoenix exceptions merely to continue with the second experiment.
  - Do not inspect private Phoenix clients, IDs, or constants.

- [ ] Run the network-free fixture mode before any live call:

```bash
uv run python tests/manual_quality/basic_agent_evaluation.py --check-cases
```

Expected: `cases.json is valid` and exit 0. Any other argument prints the usage string to stderr and exits 2.

### Task 4: Synchronize repository guidance

**Files:** Modify `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`

- [ ] Add the same facts to all three files:

```markdown
The old `app/evals/` pilot is gone. Manual quality evaluation consists of
`app/tests/manual_quality/basic_agent_evaluation.py` and `cases.json`. The
script records one live expert experiment and one overlapping full-orchestrator
experiment in Phoenix, including each LLM judge's classification explanation.
It is not collected by pytest, run in CI, or copied into runtime images. Live
dependency or judge failures are invalid and unscored; results are advisory.
Phoenix retains unredacted prompts, fetched article text, answers, and judge data.
```

- [ ] Document the command:

```bash
docker compose up -d phoenix
cd app
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces \
  uv run python tests/manual_quality/basic_agent_evaluation.py
```

State that the root `.env` supplies `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY`; `DATABASE_URL` is not required because the manual orchestrator graph has no checkpointer.

### Task 5: Run offline verification and commit

- [ ] Confirm the live script is not collected:

```bash
cd app
uv run pytest --collect-only -q
```

Expected: no node ID from `tests/manual_quality/`.

- [ ] Run the network-free gates:

```bash
uv run python tests/manual_quality/basic_agent_evaluation.py --check-cases
uv run ruff check tests/manual_quality/basic_agent_evaluation.py
uv run ruff format tests/manual_quality/basic_agent_evaluation.py --check
uv run mypy --strict tests/manual_quality/basic_agent_evaluation.py
uv run pytest -q
uv run make lint
```

Expected: case validation succeeds and all static/regression checks pass. Do not run the live experiment during ordinary verification because it incurs Brave and OpenAI cost.

- [ ] Verify scope from the repository root:

```bash
git diff --check
git status --short
rg -n 'from evals|import evals|offline evaluation pilot' \
  app AGENTS.md CLAUDE.md .github/copilot-instructions.md
```

Expected: no whitespace errors, only planned changes, and no obsolete implementation/guidance references.

- [ ] Commit the cohesive replacement:

```bash
git add -A app/evals app/tests/unit_tests/evals app/tests/manual_quality \
  app/pyproject.toml docs/evals docs/plans/2026Sep01_plan_offline-eval-pilot_v1.md \
  docs/plans/2026Sep01_plan_offline-eval-pilot_v2.md \
  AGENTS.md CLAUDE.md .github/copilot-instructions.md
git commit -m "test: replace evaluation pilot with lean Phoenix smoke checks"
```

---

## Optional Human-Authorized Live Verification

After the user confirms the external cost, run the documented command once. Success means both experiments have one task result and all expected evaluations; it does not mean the agent passed a release threshold. Review the stored output and explanations in Phoenix at `http://127.0.0.1:6006` before changing rubrics or adding cases.

## Changelog from previous plan

- Replaced Python case constants with one Git-owned `cases.json` using Phoenix `input`/`output` semantics.
- Reduced new evaluation artifacts from four files to two.
- Removed package markers and the entire manual-runner unit-test package.
- Removed adapter factories, fake graphs, CLI mock tests, private `DRY_RUN_` checks, and detailed Phoenix result-shape testing.
- Removed embedded-server, duplicate-instrumentation, trace-query, DataFrame evaluation, and manual annotation-upload ideas from the supplied generic example because this repository already has tracing and uses Phoenix experiments.
- Kept the two-stage task-then-evaluate sequence because it is the smallest reliable way to prevent graph failures from being judged.
- Made JSON `output` useful as evaluator reference truth instead of a mutable destination for generated results.
- Added compact console printing of each classification and explanation.
- Consolidated implementation into one cohesive commit and one offline verification gate.

## Open questions and rejected objections

**Open questions:** None. The latest user request settles the storage shape and desired judge explanation.

**Rejected: write generated answers back to `cases.json`.** That would make a versioned input fixture mutable and blur reference truth with one stochastic live result. Phoenix already persists generated answers and sources.

**Rejected: copy `px.launch_app()` from the generic example.** The installed environment does not include the full Phoenix server API, and Compose already owns the persistent Phoenix service.

**Rejected: call `LangChainInstrumentor().instrument()` directly.** `init_tracing()` already registers Phoenix with `auto_instrument=True`; a second call risks duplicate spans.

**Rejected: evaluate by re-querying all `LangGraph` spans.** Span names are framework/version-sensitive and can select stale runs. Phoenix experiments already link each fixed input, task output, trace, score, and explanation.

**Rejected: remove the task/evaluation split.** Phoenix can represent task errors, but the settled policy requires failures to remain unscored. Validating the one task run before invoking judges preserves that policy with minimal code.
