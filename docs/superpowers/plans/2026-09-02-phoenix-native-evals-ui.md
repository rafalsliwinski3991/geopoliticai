# Phoenix Native Evaluations UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop formatting evaluation scores and explanations in `basic_agent_evaluation.py`; persist the same validated results in Phoenix and make its native experiment Evaluations view the reviewer-facing output.

**Architecture:** Keep the existing datasets, graph adapters, evaluators, and two-phase experiment flow. The task phase remains separate so a failed graph run is rejected before any evaluator is invoked; the evaluation phase remains client-side because Phoenix server-side dataset evaluators run automatically only for experiments launched from the Playground. Replace the custom terminal report with silent completeness validation, enable the Phoenix client's native evaluation summary, and rely on its emitted experiment URL to lead reviewers to scores, labels, explanations, outputs, and traces in Phoenix.

**Tech Stack:** Python 3.10+, `arize-phoenix-client` 3.3.x, `arize-phoenix-evals` 3.6.x, Phoenix server 20.4.0, LangGraph, pytest, Ruff, mypy strict

**Spec:** `docs/brainstorming/2026Sep02_brainstorm_v1_basic-agent-evaluation.md`, with the reviewer-output refinement requested on 2026-09-02

## Global Constraints

- Keep the two current datasets and all four evaluator signals unchanged: expert `groundedness` and `usefulness`; orchestrator `route_correct` and `rewrite_quality`.
- Keep the pinned judge model `gpt-4o-mini-2024-07-18`, one repetition, zero retries, concurrency one, and the 180-second Phoenix timeout.
- Preserve the two-phase task/evaluation flow so a failed or malformed task run remains invalid and receives no evaluation.
- Preserve hard failure for missing, failed, malformed, or explanation-less evaluator results; changing the presentation must not turn invalid judge output into a successful run.
- Use Phoenix's dataset experiment Evaluations view as the canonical review surface. Do not add duplicate span or trace annotations: experiment evaluations are already persisted against experiment runs and shown by the experiment UI.
- Do not move evaluator definitions into Phoenix's server-side dataset Evaluators tab. Phoenix documentation states that attached dataset evaluators run automatically only for experiments started from the UI Playground; this script executes arbitrary local LangGraph tasks programmatically.
- Do not add dependencies, change `cases.json`, alter application graph code, or modify `.env`.
- Keep the runner manual, outside pytest collection, CI, and runtime images; its results remain advisory and unredacted.
- Update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together and keep their manual-evaluation facts consistent.

## Documentation Basis

- Context7 library `/websites/arize_phoenix`, [Using Evaluators](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/using-evaluators): programmatic experiments pass evaluators to `run_experiment`, and Phoenix persists their results for its Experiments UI.
- Context7 library `/websites/arize_phoenix`, [Dataset Evaluators](https://arize.com/docs/phoenix/datasets-and-experiments/how-to-experiments/how-to-dataset-evaluators): UI-attached evaluators run automatically only for experiments launched from the Phoenix UI, so they cannot replace the local LangGraph runner.
- Installed `arize-phoenix-client` 3.3.0 API: `AsyncClient.experiments.run_experiment` emits dataset/experiment links, while `evaluate_experiment(..., print_summary=True)` emits the native evaluation count summary and returns the persisted evaluation runs for validation.

## File Map

- Modify `app/tests/manual_quality/basic_agent_evaluation.py` — remove custom result rendering, retain silent result validation, and use the Phoenix client's native evaluation summary and experiment link.
- Modify `AGENTS.md` — direct reviewers to Phoenix's native experiment Evaluations view and describe terminal output accurately.
- Modify `CLAUDE.md` — mirror the same operational facts.
- Modify `.github/copilot-instructions.md` — mirror the same operational facts.
- No new runtime modules, fixtures, datasets, or dependencies.

---

### Task 1: Specify the native-output contract with a focused source test

**Files:**

- Create: `app/tests/unit_tests/test_manual_quality_evaluation.py`
- Test: `app/tests/unit_tests/test_manual_quality_evaluation.py`

**Interfaces:**

- Consumes: the source file at `app/tests/manual_quality/basic_agent_evaluation.py`.
- Produces: a regression contract that the live runner has no custom evaluation-result renderer, asks Phoenix to print its native evaluation summary, and does not print experiment IDs or score/explanation lines itself.

- [ ] **Step 1: Write a failing AST-based regression test**

Create `app/tests/unit_tests/test_manual_quality_evaluation.py`:

```python
"""Regression checks for the manual Phoenix evaluation runner's UI boundary."""

from __future__ import annotations

import ast
from pathlib import Path


RUNNER_PATH = (
    Path(__file__).parents[1] / "manual_quality" / "basic_agent_evaluation.py"
)


def test_live_results_use_phoenix_native_output() -> None:
    """Keep result presentation in Phoenix instead of custom terminal rendering."""
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    printed_expressions = [
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        and node.args
    ]
    printed_output = "\n".join(printed_expressions)
    evaluate_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "evaluate_experiment"
    ]

    assert "validate_and_print_evaluations" not in function_names
    assert "expert experiment:" not in printed_output
    assert "orchestrator experiment:" not in printed_output
    assert "score=" not in printed_output
    assert "explanation:" not in printed_output
    assert "Advisory reviewer evidence" not in printed_output
    assert len(evaluate_calls) == 1
    assert any(
        keyword.arg == "print_summary"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in evaluate_calls[0].keywords
    )
```

This intentionally checks only the presentation boundary. It does not import the live runner, initialize tracing, contact Phoenix, or couple unit tests to Phoenix result classes.

- [ ] **Step 2: Run the regression test and confirm the current implementation fails**

Run from `app/`:

```bash
UV_CACHE_DIR=/tmp/geopoliticai-uv-cache uv run pytest \
  tests/unit_tests/test_manual_quality_evaluation.py -q
```

Expected: FAIL because `validate_and_print_evaluations` still exists and `evaluate_experiment(..., print_summary=False)` suppresses Phoenix's native summary.

- [ ] **Step 3: Commit the failing contract**

```bash
git add app/tests/unit_tests/test_manual_quality_evaluation.py
git commit -m "test: define Phoenix native eval output contract"
```

---

### Task 2: Replace custom result rendering with Phoenix-native presentation

**Files:**

- Modify: `app/tests/manual_quality/basic_agent_evaluation.py:278-415`
- Test: `app/tests/unit_tests/test_manual_quality_evaluation.py`

**Interfaces:**

- Consumes: `RanExperiment["evaluation_runs"]`, the expected evaluator-name set, and the set of evaluators that require explanations.
- Produces: `validate_evaluations(result, *, expected_names, explanation_names) -> None`, which raises on invalid persisted evaluator results and emits no output.
- Produces: `run_experiment_case(...) -> None`; Phoenix's client owns progress, experiment URL, and summary output.

- [ ] **Step 1: Make evaluator validation silent**

Rename `validate_and_print_evaluations` to `validate_evaluations`, replace its docstring, and delete only the result-formatting statements. Keep every completeness and type check:

```python
def validate_evaluations(
    result: RanExperiment,
    *,
    expected_names: set[str],
    explanation_names: set[str],
) -> None:
    """Reject incomplete evaluations without duplicating Phoenix UI output."""
    matching = [run for run in result["evaluation_runs"] if run.name in expected_names]
    actual_names = {run.name for run in matching}
    if actual_names != expected_names or len(matching) != len(expected_names):
        raise RuntimeError(
            f"Expected evaluations {sorted(expected_names)}, got {sorted(actual_names)}"
        )

    for run in matching:
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
```

Do not weaken the numeric-score check for `route_correct`: Phoenix normalizes the boolean evaluator result to numeric `0` or `1` plus a string label before this function sees it.

- [ ] **Step 2: Let Phoenix render the evaluation summary**

In `run_experiment_case`, change the return annotation to `None`, enable only the evaluation call's native summary, validate silently, and do not return the result:

```python
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
) -> None:
    """Record one valid graph run and its evaluations for review in Phoenix."""
    dataset = await client.datasets.create_dataset(
        name=dataset_name,
        examples=[example],
        dataset_description="Manual advisory quality smoke case",
        timeout=PHOENIX_TIMEOUT_SECONDS,
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
        print_summary=True,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
        retries=0,
    )
    validate_evaluations(
        result,
        expected_names=expected_names,
        explanation_names=explanation_names,
    )
```

Keep `print_summary=False` on the task-only call: the Phoenix SDK already prints the dataset and experiment links when it starts the experiment, and the reviewer needs the native evaluation summary after scoring, not a task-only count before scoring.

- [ ] **Step 3: Remove the caller's custom live-result report**

In `main`, await both calls without assigning their return values and delete the three final `print(...)` calls:

```python
    await run_experiment_case(
        client=client,
        dataset_name="geopoliticai-expert-smoke-v1",
        example=cases["expert"],
        task=run_expert,
        evaluators=build_expert_evaluators(judge),
        expected_names={"groundedness", "usefulness"},
        explanation_names={"groundedness", "usefulness"},
        experiment_name=f"expert-quality-{timestamp}",
    )
    await run_experiment_case(
        client=client,
        dataset_name="geopoliticai-orchestrator-smoke-v1",
        example=cases["orchestrator"],
        task=run_orchestrator,
        evaluators=build_orchestrator_evaluators(judge),
        expected_names={"route_correct", "rewrite_quality"},
        explanation_names={"rewrite_quality"},
        experiment_name=f"orchestrator-quality-{timestamp}",
    )
```

Leave the `--check-cases` success message and invalid-argument usage message unchanged. They are CLI diagnostics, not a competing renderer for live evaluation results.

- [ ] **Step 4: Run the focused regression test**

Run from `app/`:

```bash
UV_CACHE_DIR=/tmp/geopoliticai-uv-cache uv run pytest \
  tests/unit_tests/test_manual_quality_evaluation.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the network-free runner check**

Run from `app/`:

```bash
UV_CACHE_DIR=/tmp/geopoliticai-uv-cache uv run python \
  tests/manual_quality/basic_agent_evaluation.py --check-cases
```

Expected: exit 0 with `cases.json is valid`.

- [ ] **Step 6: Commit the implementation**

```bash
git add app/tests/manual_quality/basic_agent_evaluation.py \
  app/tests/unit_tests/test_manual_quality_evaluation.py
git commit -m "refactor: use Phoenix native eval presentation"
```

---

### Task 3: Document the Phoenix-native review workflow

**Files:**

- Modify: `AGENTS.md:146-161`
- Modify: `CLAUDE.md:102-117`
- Modify: `.github/copilot-instructions.md:102-117`

**Interfaces:**

- Consumes: the unchanged manual command and two experiment names emitted by the Phoenix client.
- Produces: consistent reviewer instructions across all three agent-guidance files.

- [ ] **Step 1: Update all three guidance files together**

Replace the sentence describing recorded classifications and explanations with these facts, adapted only for the surrounding prose:

```markdown
The script records one live expert experiment and one overlapping
full-orchestrator experiment in Phoenix. It does not render scores or judge
explanations itself: follow the Phoenix client experiment links and review each
experiment's native Evaluations view, which contains the score, label,
explanation, task output, and linked traces. The terminal retains only Phoenix
SDK progress/summary output and CLI diagnostics.
```

Keep the existing statements about manual execution, advisory status, invalid failures, unredacted retention, credentials, and `DATABASE_URL` unchanged.

- [ ] **Step 2: Verify that the three descriptions remain factually aligned**

Run from the repository root:

```bash
rg -n "native Evaluations view|Phoenix SDK progress/summary" \
  AGENTS.md CLAUDE.md .github/copilot-instructions.md
```

Expected: both phrases appear once in each file.

- [ ] **Step 3: Commit the documentation update**

```bash
git add AGENTS.md CLAUDE.md .github/copilot-instructions.md
git commit -m "docs: point manual eval review to Phoenix UI"
```

---

### Task 4: Verify the complete change, including one live Phoenix run

**Files:**

- Verify: `app/tests/manual_quality/basic_agent_evaluation.py`
- Verify: `app/tests/unit_tests/test_manual_quality_evaluation.py`
- Verify: `AGENTS.md`
- Verify: `CLAUDE.md`
- Verify: `.github/copilot-instructions.md`

**Interfaces:**

- Consumes: the repository root `.env`, the Compose Phoenix server at `127.0.0.1:6006`, live OpenAI and Brave credentials, and the two fixed cases.
- Produces: two valid Phoenix experiments whose native Evaluations views expose all four expected signals without a custom terminal score report.

- [ ] **Step 1: Run unit tests**

Run from `app/`:

```bash
UV_CACHE_DIR=/tmp/geopoliticai-uv-cache uv run make test
```

Expected: all unit tests pass.

- [ ] **Step 2: Run formatting, lint, and strict type checks**

Run from `app/`:

```bash
UV_CACHE_DIR=/tmp/geopoliticai-uv-cache uv run make lint
```

Expected: Ruff formatting/checks and mypy strict checks pass.

- [ ] **Step 3: Start Phoenix and run the live manual evaluation**

Run from the repository root:

```bash
docker compose up -d phoenix
cd app
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces \
  UV_CACHE_DIR=/tmp/geopoliticai-uv-cache \
  uv run python tests/manual_quality/basic_agent_evaluation.py
```

Expected terminal behavior:

- Phoenix prints a dataset-experiments URL and a direct experiment URL for each case.
- Phoenix prints native task/evaluation progress and an evaluation-count summary.
- The script does not print hand-formatted `score=...`, `explanation: ...`, or final `expert experiment:` / `orchestrator experiment:` lines.
- Any graph, judge, or Phoenix failure exits non-zero and is not reported as a valid scored observation.

- [ ] **Step 4: Verify both native Evaluations views**

Open each direct experiment URL printed by Phoenix and confirm:

- `expert-quality-<UTC timestamp>` has exactly `groundedness` and `usefulness`.
- `orchestrator-quality-<UTC timestamp>` has exactly `route_correct` and `rewrite_quality`.
- Every evaluation has a numeric score and label.
- `groundedness`, `usefulness`, and `rewrite_quality` have non-empty explanations.
- Each experiment run exposes its task output and linked task/evaluator traces.

This browser check is required because the requested behavior is a Phoenix UI presentation contract that cannot be proven by the network-free unit test.

- [ ] **Step 5: Review the final diff for scope**

Run from the repository root:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only the runner, its focused unit test, and the three synchronized guidance files are implementation changes. The plan file itself may also be present if it was not committed separately.
