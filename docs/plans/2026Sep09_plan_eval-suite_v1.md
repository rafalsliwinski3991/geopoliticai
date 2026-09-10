# Plan — Edge-case eval suite with an OpenRouter judge

Implements the eval half of
`docs/brainstorming/2026Sep09_brainstorm_v2_tests-and-openrouter-evals.md`.
Depth: **full**. It changes the judge provider, adds a required environment
variable and repository secrets, adds a GitHub Actions workflow, rewrites the
case schema, and changes `CLAUDE.md`. Six ordered commits.

**Shape: trimmed.** After review, the user chose the trimmed shape over the
plan's original scope. The four deterministic edge cases are dropped, and the
judge swap is ordered ahead of the rubric rewrite so each can be measured
separately. See "Shape decision" near the end for the evidence and what was
given up.

The unit-test half is `docs/plans/2026Sep09_plan_unit-test-layout_v1.md`. The
two plans share no files.

## Scope summary

**Rewritten.** `app/tests/manual_quality/basic_agent_evaluation.py` keeps its
shape as a standalone script with one `evaluate_experiment` call site, and
changes in four ways: the judge becomes a pinned OpenRouter free model, the
Phoenix destination becomes configurable, cases come from a list rather than
two named keys, and judge failures are recorded rather than fatal.

**Rewritten.** `app/tests/manual_quality/cases.json` becomes a list of entries,
each naming the agent it runs against. It grows from 2 judged cases to 6, all
of them cases where a judge can see something a `assert` cannot.

**Not built.** The four deterministic cases (`orchestrator-other-routing`,
`reporter-refusal`, `reporter-cancel`, `reporter-revision-cap`) and the
`expected_notice` CODE evaluator. Those paths keep their existing coverage in
the unit and integration suites, which assert strictly more than a live eval
case can observe.

**Added.** `.github/workflows/evals.yml`, dispatch-only.

**Kept deliberately.** The standalone-script shape, on the user's stated
rationale that Phoenix's pytest plugin would weld live, money-spending evals
into the same runner as the free unit tests. The fully-live dependency policy,
on the user's rationale that integration wiring is what unit tests cannot
catch. Phoenix as the only destination, Arize AX rejected because the user's
requirement was hosted visibility of CI results.

**Deleted.** The `JUDGE_MODEL = "gpt-4o-mini-2024-07-18"` value, `CASE_NAMES`,
`CASE_FIELDS`, and the `run.error` raise inside `validate_evaluations`.
`phoenix_base_url()` is **kept** unchanged: its `/v1/traces` suffix stripping
works for a Phoenix Cloud endpoint exactly as it does for the Compose one.

### Why the deterministic cases are not built

Recorded because the brainstorm settled the opposite, and the reversal was the
user's after seeing this evidence.

Every eval case enters through `classify`, a live structured model call
(`src/agents/orchestrator/nodes/classify.py:46`). An eval cannot pin that
decision, while `tests/integration_tests/test_orchestrator_graph.py:75-81`
does, with a monkeypatch. A classifier that routes a report request to the
expert branch spends three Brave batches and a report-model call, returns an
answer rather than a notice, and reddens the workflow with nothing regressed.

The existing offline tests also assert more than an eval case can see.
`tests/integration_tests/test_reporter_graph.py:222` asserts `state.next == ()`
at the revision cap, catching an outline node that would leave the thread
paused forever. It also pins the outline call count and the absence of a write
call (`:225-226`). An eval case reads only the final message string.

And the layers with real integration risk are never exercised by this runner,
which calls compiled graphs directly: `api.py`'s SSE framing and status
mapping, the `AsyncPostgresSaver` production actually uses, and
`agents/reporter/intent.py`, which turns a typed resume line into an action
dict.

### Three findings where the code contradicts the brainstorm

These were established by reading the source, and the code wins.

1. **Truncation cannot be an eval case and should be dropped from the list.**
   The brainstorm names truncation as a deterministic edge case. Truncation
   lives in `app/src/api.py::_generate` at the delivery layer, gated on
   `MAX_ANSWER_CHARS = 50_000` (`api.py:49`, `api.py:474`). The eval runner
   invokes compiled graphs directly and never touches the ASGI app, so no
   graph-level task can reach it. Reaching it would also mean producing a
   50,000-character answer from a live model on demand, which is neither cheap
   nor reliable. It is already covered deterministically by
   `test_a_stream_of_exactly_max_answer_chars_is_not_truncated`
   (`tests/unit_tests/test_api.py:447`) and the over-cap case at
   `test_api.py:488`. **Dropped from the eval case list**, leaving four
   deterministic paths, not five. The trim later removed all four of those as
   well, so this finding is now historical: it explains why truncation was
   never a candidate even under the original scope.

2. **The reporter cases need a checkpointer that the current runner does not
   build.** The brainstorm assumes cancel and revision-cap cases can run like
   the existing orchestrator case, which calls the module-level
   `agents.orchestrator.graph.graph`. That object is built by
   `graph = build_graph()` at `graph.py:59` with **no checkpointer**. Every
   reporter path pauses at `gate`, which calls `interrupt()`, and an interrupt
   cannot be resumed without a saver. Both `build_graph` functions already take
   a `checkpointer` argument documented as the hook for driving them with an
   `InMemorySaver` (`orchestrator/graph.py:19-28`,
   `reporter/graph.py:29-37`), and `langgraph.checkpoint.memory.InMemorySaver`
   is importable in this venv. **Reporter eval tasks build their own graph with
   an `InMemorySaver`** rather than using the module-level one.

3. **Per-case judge failure recording needs no new machinery.** The brainstorm
   treats "record the failure per case and continue" as work. Phoenix already
   does it: `_run_single_evaluation_sync` catches `BaseException` from an
   evaluator, records it on the span, and submits the evaluation with the error
   (`phoenix/client/resources/experiments/__init__.py:1994-2010`). The result
   surfaces as `run.error`, which the current `validate_evaluations` reads and
   **raises on**. The change is therefore a deletion plus a counter, not new
   error plumbing.

## File responsibilities

| File | Responsibility |
| --- | --- |
| `app/tests/manual_quality/basic_agent_evaluation.py` | The whole runner: case loading, per-agent tasks, evaluators, judge construction, Phoenix destination, threshold enforcement, process exit code. |
| `app/tests/manual_quality/cases.json` | Case data only. A list of entries, each naming its agent, input, expected output, and metadata. No behaviour. |
| `.github/workflows/evals.yml` | Dispatch-only trigger, secret injection, and nothing else. It runs the script and reports its exit code. |
| `CLAUDE.md` | Records the new environment variable, the workflow, and the judge provider, so the guidance stays true. |
| `app/tests/unit_tests/test_manual_quality_evaluation.py` | Unchanged in intent. It guards the Phoenix-native output boundary and must keep passing. |

## Ordered commits

Mechanical and isolated first, the case-schema rewrite in the middle, the new
live cases last. Every commit leaves the repo importable and `make test`
green, because none of the runner's behaviour is exercised by unit tests other
than the AST-level boundary check.

### Commit 1 — judge moves to OpenRouter

**Files.** `basic_agent_evaluation.py`.

**Safe here** because it changes one constant and one constructor call, and
touches no case data or control flow.

**Before** (`basic_agent_evaluation.py:26` and its use in `main`):

```python
JUDGE_MODEL = "gpt-4o-mini-2024-07-18"
...
    judge = LLM(provider="openai", model=JUDGE_MODEL)
```

**After:**

```python
# Pinned, not `openrouter/free`. Phoenix's OpenAI adapter sends the model name
# it was configured with and never reads the resolved model back off the
# response (`phoenix/evals/llm/adapters/openai/adapter.py`), so a router id
# would leave every recorded score attributed to the router and make scores
# uncomparable across runs. On retirement, swap for another free model that
# supports EITHER structured outputs or tool calling: the adapter tries a
# strict `json_schema` first and falls back to tool calling on a
# `BadRequestError` (`phoenix/evals/llm/adapters/openai/adapter.py:130-186`),
# so the viable pool is wider than a `structured_outputs` filter suggests.
JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
...
    judge = LLM(
        provider="openai",
        model=JUDGE_MODEL,
        api_key=require_env_value("OPENROUTER_API_KEY"),
        base_url=OPENROUTER_BASE_URL,
    )
```

`LLM.__init__` forwards unknown keyword arguments to the underlying SDK client
constructor and documents `api_key` and `base_url` explicitly
(`phoenix/evals/llm/wrapper.py:155-170`), so this needs no new dependency.

Add the small helper next to `phoenix_base_url`, because `require_env` from
`config.py` checks presence but returns nothing:

```python
def require_env_value(name: str) -> str:
    """Return a required environment variable's value, or fail loudly."""
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(f"{name} must be set")
    return value
```

Extend the existing `require_env` call in `main` to cover the new key:

```python
    require_env((*REQUIRED_ENV_VARS, "PHOENIX_COLLECTOR_ENDPOINT", "OPENROUTER_API_KEY"))
```

**Test.** `cd app && make lint && make test`, then a live local run of the two
**existing** cases against the **existing** rubrics.

This ordering is the point. The judge changes here and the ruler changes in
commit 5, so this run measures the new judge against the scale the old judge
was scored on. Record the scores. Without this run, any later score movement
has two candidate causes and no way to separate them.

### Commit 2 — Phoenix destination becomes configurable

**Files.** `basic_agent_evaluation.py`.

**Safe here** because local behaviour is unchanged when the new variables are
unset.

Phoenix Cloud is reached with the same client, at a base URL of the form
`https://app.phoenix.arize.com/s/<space>` plus an API key. The existing
`phoenix_base_url()` derives the REST base from
`PHOENIX_COLLECTOR_ENDPOINT` by stripping a required `/v1/traces` suffix, and
that derivation still holds for Cloud. Keep it, and add only the key.

**Before:**

```python
    client = AsyncClient(base_url=phoenix_base_url())
```

**After:**

```python
    # `PHOENIX_API_KEY` is unset locally, where the Compose Phoenix is open, and
    # set from a repository secret in the workflow, where Phoenix Cloud requires
    # it. One client either way: Cloud speaks the same API as the container.
    client = AsyncClient(
        base_url=phoenix_base_url(),
        api_key=os.getenv("PHOENIX_API_KEY") or None,
    )
```

Tracing needs **no** change at all, contrary to an earlier draft of this plan.
`phoenix.otel`'s span exporter, when `register()` passes no explicit headers —
and `tracing.py:init_tracing()` never does — merges
`get_env_phoenix_auth_header()`, which builds `{"authorization": "Bearer
<PHOENIX_API_KEY>"}` from `PHOENIX_API_KEY` alone
(`phoenix/otel/settings.py:351-366`, `phoenix/otel/otel.py:588-596`). The one
`PHOENIX_API_KEY` secret therefore authenticates both the REST client and the
OTLP exporter. No `PHOENIX_CLIENT_HEADERS`, no edit to `tracing.py`.

**Test.** `cd app && make lint && make test`, then one live local run to prove
the unset-key path is unchanged.

### Commit 3 — cases become a list

**Files.** `cases.json`, `basic_agent_evaluation.py`.

**Safe here** because the two existing cases are carried across unchanged; only
their container and the loader change.

**Before** (`basic_agent_evaluation.py:24-25` and `load_cases`):

```python
CASE_NAMES = {"expert", "orchestrator"}
CASE_FIELDS = {"id", "input", "output", "metadata"}

def load_cases() -> dict[str, dict[str, Any]]:
    raw: object = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != CASE_NAMES:
        raise ValueError("cases.json must contain exactly expert and orchestrator")
    ...
```

**After:**

```python
CASE_FIELDS = {"agent", "id", "input", "output", "metadata"}
KNOWN_AGENTS = {"expert", "orchestrator", "reporter"}

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
```

`cases.json` becomes a list of the two existing objects, each gaining
`"agent": "expert"` and `"agent": "orchestrator"` respectively. Content is
otherwise byte-identical.

`main` changes from two hardcoded `run_experiment_case` calls to a loop over
the list, dispatching on `case["agent"]` through a table of task functions,
evaluator builders, and expected evaluation names. The single
`evaluate_experiment` call site inside `run_experiment_case` is preserved,
because `test_manual_quality_evaluation.py:32` asserts there is exactly one and
that it passes `print_summary=True`.

**Test.** `cd app && make lint && make test`, then a live local run of the two
carried-over cases producing the same evaluator names as before.

### Commit 4 — judge failures recorded, thresholds enforced

**Files.** `basic_agent_evaluation.py`.

**Safe here** because it changes only what the runner does with results it
already receives.

Phoenix catches evaluator exceptions per run and surfaces them as `run.error`.
The runner currently raises on the first one.

**Before** (`validate_evaluations`):

```python
    for run in matching:
        if run.error:
            raise RuntimeError(f"{run.name} failed: {run.error}")
```

**After.** `validate_evaluations` returns a tally instead of raising on a judge
error, and the process decides at the end.

```python
# Two rules, not one number. Phoenix scores a bool evaluator as 0.0 or 1.0
# (`phoenix/client/resources/experiments/__init__.py:579`), so a *passing* CODE
# evaluator scores 1.0. A single threshold of 3.0 applied across both kinds
# would fail every run, including a perfect one.
JUDGED_SCORE_THRESHOLD = 3.0  # Provisional. No historical scores exist;
                              # revisit after the first runs.
JUDGED_EVALUATORS = {"groundedness", "usefulness", "rewrite_quality"}
# CODE evaluators fail on a falsy score, judged evaluators on < 3.0.


@dataclass(frozen=True)
class CaseOutcome:
    """What one case produced, so `main` can decide the exit code once."""

    case_id: str
    scored: int
    judge_errors: int
    below_threshold: list[str]
```

The plumbing this needs, which an earlier draft left implicit:
`validate_evaluations` gains a `case_id` parameter and returns a `CaseOutcome`
instead of `None`; `run_experiment_case` changes from `-> None` to
`-> CaseOutcome`, gains `case_id`, `case_count` and `experiment_metadata`
parameters, and returns what `validate_evaluations` handed it; `main`
accumulates the returned outcomes in a list.

`validate_evaluations` keeps rejecting a *structurally* invalid result, which
is a bug in the runner rather than a flaky judge: a missing evaluator name, a
non-numeric score, a blank label, or a missing explanation where one is
required. It stops raising on `run.error`, counting it instead, and collects
the names of judged evaluators scoring below `SCORE_THRESHOLD`.

A CODE evaluator fails when its score is `0.0`; a judged evaluator fails when
its score is below `JUDGED_SCORE_THRESHOLD`. The two rules are keyed on whether
the evaluator's name is in `JUDGED_EVALUATORS`. This is the correction to a
defect the review caught: a passing bool scores 1.0, so one shared threshold
would have made every run red.

`main` accumulates one `CaseOutcome` per case, records the totals on the
experiment metadata so a partially scored run is never silently compared with a
complete one, and exits non-zero if any case has a judge error or a
below-threshold score:

```python
    failures = [o for o in outcomes if o.judge_errors or o.below_threshold]
    if failures:
        for outcome in failures:
            logger.error(
                "%s: %d judge errors, below threshold: %s",
                outcome.case_id,
                outcome.judge_errors,
                ", ".join(outcome.below_threshold) or "none",
            )
        raise SystemExit(1)
```

The experiment metadata carries the counts. It is a parameter of
`client.experiments.run_experiment` (`resources/experiments/__init__.py:752`)
and **not** of `create_dataset`, which has no such parameter and would raise
`TypeError`. `run_experiment_case` gains an `experiment_metadata` parameter and
threads it into its existing `run_experiment` call:

```python
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
        retries=0,
    )
```

**Do not parameterize `print_summary`.** `test_manual_quality_evaluation.py`
asserts the single `evaluate_experiment` call carries a literal
`ast.Constant(value=True)` for that keyword. Threading it through a variable
or a parameter fails that test even though runtime behaviour is unchanged.

**Test.** `cd app && make lint && make test`. Then a live local run, and a
second run with `OPENROUTER_API_KEY` set to an invalid value, which must
produce recorded judge errors, a non-zero exit, and still leave the task
outputs in Phoenix.

### Commit 5 — generalised rubrics and four new judged cases

**Files.** `basic_agent_evaluation.py`, `cases.json`.

**Safe here** because commit 1's run has already recorded the new judge's
scores against the old rubrics, so this commit's effect on scores is
attributable to the rubric change alone.

This is the largest and most editorial commit. It has two halves, and the
rubric half must land first.

#### Half one — generalise the rubrics

Two of the three rubrics have the Finland and Sweden answer key written into
their own scoring rungs, so they cannot score any other question.

- `GROUNDEDNESS_PROMPT` (`basic_agent_evaluation.py:50-55`) is already generic.
  **Unchanged.**
- `USEFULNESS_PROMPT` (`:79-80`) labels 4 and 5 name "the security-policy
  change and April 2023 accession" and "the invasion, abandonment of
  non-alignment, accession process, and April 2023 completion". Both rungs must
  be restated against the case's own `must_address` list, which the evaluator
  already receives as `requirements`.
- `REWRITE_QUALITY_PROMPT` (`:101-105`) names Sweden in every label and
  Finland's 2023 date in labels 3 and 5. Every rung must be restated against
  the case's own `expected_intent`, which the evaluator already receives.

Generalised rungs for `USEFULNESS_PROMPT`, replacing labels 4 and 5:

```text
4: covers every required point with a minor omission or a small loss of precision.
5: covers every required point precisely, with the causal connections between them made explicit and no material omission.
```

Generalised rungs for `REWRITE_QUALITY_PROMPT`, replacing all five:

```text
1: does not resolve the referent of the last user turn, or changes the user's meaning.
2: names the referent but stays materially ambiguous, or asks a different question.
3: is self-contained but loosely preserves the intent, or imports an assumption the history does not support.
4: matches the expected intent with a small loss of nuance.
5: fully matches the expected intent, self-contained, importing nothing the history does not support.
```

**This changes what a score means.** A 4 recorded after this commit is not the
same measurement as a 4 recorded before it. Commit 1's run is the record of the
old scale; treat scores from before this commit and after it as two series.

#### Half two — four new judged cases

Six judged cases total, up from two. Every one is a case where a judge sees
something an assertion cannot.

| Case | Agent | Judged on |
| --- | --- | --- |
| `expert-finland-nato-v1` | expert | groundedness, usefulness (existing) |
| `expert-<second-topic>` | expert | groundedness, usefulness |
| `expert-<third-topic>` | expert | groundedness, usefulness |
| `orchestrator-sweden-follow-up-v1` | orchestrator | route_correct, rewrite_quality (existing) |
| `orchestrator-<ambiguous-follow-up>` | orchestrator | route_correct, rewrite_quality |
| `reporter-approved-report` | reporter | report_fidelity |

The two expert topics and the second orchestrator history are editorial and
must be chosen by the user, not invented during implementation. They should be
geopolitical questions with sources inside the allow-list, and the follow-up
history should be one whose referent is genuinely ambiguous without the prior
turns. **Bring the proposed cases to the user before writing them into
`cases.json`.**

The reporter case is the only one needing the resume machinery, and it is the
only eval coverage the reporter agent gets at all. It drives the approve path
and asks the judge whether the written report follows the outline the user
approved, which is not checkable by assertion.

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

async def run_reporter_thread(input: dict[str, Any]) -> dict[str, Any]:
    """Drive a paused reporter turn to completion over an in-memory saver.

    The module-level `agents.orchestrator.graph.graph` is compiled with no
    checkpointer (`graph.py:59`), and `gate` calls `interrupt()`, so a paused
    run cannot be resumed on it. `build_graph` takes the saver for exactly this
    reason (`orchestrator/graph.py:19-28`). Verified empirically: the first
    `ainvoke` returns state plus `__interrupt__`, each `Command(resume=...)`
    returns state plus `__interrupt__` while it pauses again, and the final
    resume returns the full state with no `__interrupt__`.

    Not reusable from `run_orchestrator`, which raises on any destination
    outside `{"geopolitical", "other"}` (`basic_agent_evaluation.py:196`).
    """
    from agents.orchestrator.graph import build_graph, build_runtime_config

    graph = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id=f"manual-quality-{uuid4()}")
    messages = [message_from_record(record) for record in input["messages"]]

    result: dict[str, Any] = await graph.ainvoke({"messages": messages}, config=config)
    for reply in input["resume_actions"]:
        result = await graph.ainvoke(Command(resume=reply), config=config)

    final = result["messages"][-1]
    if not isinstance(final, AIMessage):
        raise RuntimeError("Reporter turn produced no final AI message")
    report = final.text()
    if not report.strip():
        raise RuntimeError("Reporter turn produced an empty report")
    return {"report": report}
```

`resume_actions` is a new key in that case's `input`, holding
`[{"action": "approve"}]`.

The outline the judge compares against cannot be read back off the parent
graph, because `OrchestratorState` has no outline key. The case therefore
supplies the expected shape in its own `output` as `outline_intent`, a prose
description of what the report should cover, and the judge compares the report
against that. One new rubric:

```python
REPORT_FIDELITY_PROMPT = """
Judge whether the report covers the intended outline and stays within the
research supplied in the conversation.

Intended coverage:
{outline_intent}

Report:
{report}

Choose exactly one label:
1: ignores the intended coverage, or asserts material facts the conversation never established.
2: covers a minority of the intended coverage, or contains substantial unsupported material.
3: covers most of the intended coverage with one meaningful gap or one unsupported claim.
4: covers all of the intended coverage with a minor gap or a small unsupported detail.
5: covers all of the intended coverage, in a coherent order, asserting nothing the conversation did not establish.

Give a concise evidence-based explanation for the label. Refer only to
observable content; do not provide private chain-of-thought.
"""
```

`route_correct` still needs the chained-comparison fix from the review, because
the second orchestrator case may expect a destination other than
`geopolitical`:

```python
# Before — passes only when the expected destination is "geopolitical".
    return bool(output.get("destination") == reference["destination"] == "geopolitical")

# After — compares the run against its own case's expectation.
    return bool(output.get("destination") == reference["destination"])
```

`report_fidelity` is a judged evaluator, so its name goes into
`explanation_names` and into `JUDGED_EVALUATORS`. No CODE evaluator name may
enter `explanation_names`: a CODE result is `{"score": float, "label": str}`
with no explanation key, which is why `route_correct` is already excluded.

**Test.** `cd app && make lint && make test`, then a full live local run of all
six cases with every evaluator producing a score and an explanation. Compare
the two carried-over cases against commit 1's recorded scores and expect
movement, since the ruler changed.

### Commit 6 — workflow and guidance

**Files.** `.github/workflows/evals.yml`, `CLAUDE.md`.

**Safe here** because the script it invokes is finished and locally proven.

```yaml
name: Evals

on:
  workflow_dispatch:

jobs:
  evals:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v3
        with:
          cache: true
      - name: Install dependencies
        working-directory: app
        run: uv sync --locked --dev
      - name: Run evals
        working-directory: app
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          BRAVE_SEARCH_KEY: ${{ secrets.BRAVE_SEARCH_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          PHOENIX_COLLECTOR_ENDPOINT: ${{ secrets.PHOENIX_COLLECTOR_ENDPOINT }}
          PHOENIX_API_KEY: ${{ secrets.PHOENIX_API_KEY }}
        run: uv run python tests/manual_quality/basic_agent_evaluation.py
```

`on: workflow_dispatch` only. It must never gain a `push` or `pull_request`
trigger, because every run spends real Brave and OpenAI credit.

The entrypoint filename must keep its non-`test_` prefix. `app/pyproject.toml`
has no `[tool.pytest]` section, so the existing `unit-tests.yml` workflow's
bare `uv run pytest` collects by discovery, and a `test_`-prefixed eval file
would run live evals on every push.

`CLAUDE.md`'s "Operations and validation" section gains: `OPENROUTER_API_KEY`
as required for the eval script, the dispatch-only workflow, and the note that
eval scores are recorded to local Phoenix or Phoenix Cloud depending on the
environment. The sentence stating the manual quality work "is advisory and not
part of pytest or CI" stays true and must not be deleted: the workflow is
dispatch-only and gates nothing.

**Test.** `cd app && make lint && make test`, then one dispatch of the workflow
from the GitHub UI on the feature branch, confirming a green run writes scores
to Phoenix Cloud and a deliberately lowered `SCORE_THRESHOLD` produces a red
one.

## Test plan

**No existing test dies.** The only unit test touching the runner is
`tests/unit_tests/test_manual_quality_evaluation.py`, which parses the runner's
AST and asserts the Phoenix-native output boundary. It must keep passing
unchanged, which constrains the rewrite in two concrete ways: exactly one
`evaluate_experiment` call site, and no `print` of scores, explanations, or
per-experiment headers. The `logger.error` calls added in commit 4 are not
`print`, so they do not trip it.

**New unit tests**, added in `tests/unit_tests/test_manual_quality_evaluation.py`,
all of which run without network access because they exercise the loader and
the pure helpers only:

- `load_cases` rejects a JSON object, an empty list, an entry with a missing or
  extra field, an unknown `agent` value, a blank `id`, and a duplicate `id`.
  Each asserts the specific `ValueError`, using `tmp_path` and monkeypatching
  `CASES_PATH`.
- `load_cases` accepts the real shipped `cases.json`, so the data file and its
  schema check cannot drift apart.
- `route_correct` returns `True` when a case's own expected destination
  matches, including a case expecting `other`, which the pre-fix chained
  comparison would have failed. This is the regression test for the
  highest-severity review finding.
- `require_env_value` raises when the variable is unset or blank.

**Not unit tested**, deliberately: the live tasks, the judge construction, and
the Phoenix client. Mocking them would assert the mock. Their validation is the
live local run named in each commit.

**Manual validation gate** before commit 6 is considered done: one full live
local run with every case scored, one run with a bad `OPENROUTER_API_KEY`
producing recorded judge errors and a non-zero exit, and one workflow dispatch.

## Migration and rollout notes

**Environment.** `OPENROUTER_API_KEY` is new and required by the eval script
only. It goes in the root `.env`, which is never committed and must not be
modified by the implementation; the user adds it. `PHOENIX_API_KEY` and
`PHOENIX_CLIENT_HEADERS` are optional and unset locally.

**Repository secrets**, added by the user in GitHub settings:
`OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, `OPENROUTER_API_KEY`,
`PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_API_KEY`.

**No schema or data migration.** Postgres is untouched. `cases.json` is test
data with a single reader.

**Documentation.** `CLAUDE.md` only, as described in commit 6. The brainstorm
artifact is a historical record and is not updated.

**Rollout order.** Commits 1 through 5 are safe to merge before any secret
exists, because the workflow does not exist yet and the script is run by hand.
Commit 6 requires the secrets to be in place first, or its first dispatch fails
on a missing variable.

## Open questions and rejected objections

Three reviewers read the real source. Every finding is recorded here with
whether it was accepted and why.

### Accepted and fixed in this revision

| Finding | Severity | Fix |
| --- | --- | --- |
| One `SCORE_THRESHOLD` of 3.0 across both evaluator kinds reddens every run, because Phoenix scores a *passing* bool as 1.0 (`resources/experiments/__init__.py:579`) | High | Split into `JUDGED_SCORE_THRESHOLD = 3.0` for the 1-5 judges and a falsy-score rule for CODE evaluators |
| `route_correct` is a chained comparison ending `== "geopolitical"` (`basic_agent_evaluation.py:258`), so any case expecting `other` scores False even when routing is correct | High | Commit 5 fixes it to compare the run against its own case's expectation |
| `experiment_metadata` is a parameter of `run_experiment`, not `create_dataset`; passing it to the latter raises `TypeError`, and the plan never threaded it into any call | High | Commit 4 now shows the full `run_experiment` call with the kwarg in place |
| The `CaseOutcome` plumbing did not compile into a consistent diff: no `case_id` parameter, no return path through `run_experiment_case` | Medium | Commit 4 names the signature changes explicitly |
| The reporter-refusal case had no stated task, and the obvious candidate `run_orchestrator` raises on the `report` destination (`basic_agent_evaluation.py:196`) | Medium | Commit 5 states that all three reporter cases use `run_reporter_thread`, refusal with an empty `resume_actions` |
| `PHOENIX_CLIENT_HEADERS` was unnecessary and in the wrong format: `PHOENIX_API_KEY` alone yields an `authorization: Bearer` header (`phoenix/otel/settings.py:351-366`, `otel.py:588-596`) | Medium | Line deleted from the workflow, rationale corrected |
| The "only 5 of 18 free models qualify" premise is too narrow: the adapter falls back from strict `json_schema` to tool calling on `BadRequestError` (`adapters/openai/adapter.py:130-186`) | Medium | The retirement comment now names the wider real pool |
| Scope summary said `phoenix_base_url()` was deleted while commit 2 said keep it | Low | Scope summary corrected; it is kept |

### Rejected, with the reason

- **"`unit-tests.yml` scopes pytest to `tests/unit_tests`, so the non-`test_`
  filename rule is unnecessary."** Rejected on the file itself:
  `.github/workflows/unit-tests.yml:32` runs a bare `uv run pytest` with no
  path argument. The Makefile's `test` target is scoped, but the workflow is
  not, and the workflow is what runs on every push. The rule stands and its
  stated rationale is correct.

### Verified by reviewers, no change needed

- The `InMemorySaver` plus `Command(resume=...)` mechanism was confirmed twice,
  once by reading and once by actually running the orchestrator and reporter
  graphs end to end. The six-revise count against `MAX_REVISION_ROUNDS = 5` is
  right, and the final resume always returns a completed run.
- The `notice` mechanism was verified sound: `OrchestratorState` has no
  `notice` key, so a task must synthesise one from the final message. Now moot,
  since the notice cases were cut in the trim, but the same reasoning applies
  to the surviving reporter case reading its report off `messages[-1]`.
- The deletions are structurally safe: `CASE_NAMES`, `CASE_FIELDS`,
  `JUDGE_MODEL`, `phoenix_base_url` and `route_correct` have no readers outside
  the runner.
- `LLM(...)` and `AsyncClient(...)` accept the arguments the plan passes.

### Escalated to the user, and resolved

Two reviewers independently attacked a decision the user settled in the
brainstorm, on evidence the user did not have at the time. It was put to the
user rather than reversed unilaterally. The user chose the trimmed shape. See
"Shape decision" at the end.

### Carried from the brainstorm, still unresolved

- **Phoenix Cloud free-tier limits are unverified.** Check before adding the
  `PHOENIX_COLLECTOR_ENDPOINT` and `PHOENIX_API_KEY` secrets. If Cloud is not
  viable, commit 6 falls back to leaving the workflow unable to record and the
  suite stays local-only, which does not block commits 1 through 5.
- **OpenRouter free-tier rate limits are unmeasured** against a run of this
  size. The first full run should record whether throttling occurs; if it does,
  the judged case count is the knob to turn.
- **The four new judged cases are editorial and unchosen.** Two expert topics,
  one ambiguous orchestrator follow-up, and one reporter thread with its
  `outline_intent`. Commit 5 must bring them to the user before writing them
  into `cases.json`; they are not for the implementer to invent.
- **Two of the three judge rubrics name Finland and Sweden facts inside their
  own scoring labels** (`USEFULNESS_PROMPT` labels 4 and 5,
  `REWRITE_QUALITY_PROMPT` labels 1 through 5; `GROUNDEDNESS_PROMPT` is already
  generic and stays unchanged). They must be generalised in commit 5 before being applied to any
  case other than the two they were written for. This is the single largest
  piece of judgement work in the plan and it is editorial, so the user should
  review the rewritten rubrics.
- **The pinned judge has reasoning enabled by default.** OpenRouter's
  catalogue reports `"reasoning": {"mandatory": false, "default_enabled":
  true}` for `nvidia/nemotron-3-super-120b-a12b:free`. Every judge call spends
  reasoning tokens the plan's cost model did not budget, adding latency and
  free-tier throttle pressure. Measure it on the first run; disabling reasoning
  is an extra body parameter if it proves to matter.
- **`JUDGED_SCORE_THRESHOLD = 3.0` is a guess** made with no historical scores, by the
  user's explicit decision, and is one constant to change.

## Shape decision

The user chose the **trimmed** shape after review, over the plan's original
scope and over the reviewers' more aggressive two-commit proposal.

**What was given up.** The four deterministic edge cases
(`orchestrator-other-routing`, `reporter-refusal`, `reporter-cancel`,
`reporter-revision-cap`), the `expected_notice` CODE evaluator, and the use of
`run_reporter_thread` for anything but the approve path. The brainstorm settled
Q2 in favour of building them; this reverses that, on evidence the user did not
have at the time, summarised in "Why the deterministic cases are not built"
above and established independently by two reviewers.

**What was kept, and why the reviewers' cheaper plan was not taken whole.** The
devil's advocate proposed also dropping the OpenRouter judge (commit 1), the
case-schema rewrite (commit 3) and the threshold (commit 4), leaving two
commits. The OpenRouter free-tier judge was part of the user's opening request,
so it is a requirement rather than a cost-benefit call and is not the
reviewer's to trade away. Commits 3 and 4 stay because the case count still
triples, which is what they exist to support.

**What changed in ordering.** The judge swap (commit 1) is now validated
against the *existing* rubrics before the rubrics are generalised (commit 5).
That was the reviewers' strongest point and it survives the trim: if
comparability is why the judge is pinned, the judge and the ruler must not move
in the same measurement. Commit 1's recorded run is the bridge between the two
score series.

**Still true after the trim.** The reporter agent's only eval coverage is the
single approve-path case in commit 5. If that case is also cut, the reporter is
unevaluated. This was flagged to the user when the trim was chosen.
