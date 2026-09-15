# Plan: reorganize the manual quality eval cases into four kinds

**Depth:** standard
**Implements:** `docs/brainstorming/2026Sep11_brainstorm_v1_eval-cases-per-agent.md`
**Supersedes:** `docs/plans/2026Sep11_plan_eval-case-kinds_v1.md`
**Review record:** `docs/plan-reviews/2026Sep11_plan_eval-case-kinds_review_v1.md`
**Tasks:** 5

## Review changes

| Change | Decision | Why |
|---|---|---|
| Setup turns in an `e2e` script carry `expect`, and `run_e2e` raises when the branch differs. | D1 (option B) | `OrchestratorState.destination` has no reducer, so the finished state holds only the last turn's routing. As written in v1, a turn-one misroute left every judge green while the case tested nothing it claimed to. |
| Only non-final `query` turns carry `expect`. The final turn's routing stays graded by `route_correct`. | D2 | Setup turns exist to put cited research into the thread; one on the wrong branch is a broken fixture. The final turn is the subject under test, and a misroute there should produce a zero beside the other scores, not a crash that records nothing. |
| The whole turn script, `expect` values included, is validated before the first `ainvoke`. | D2 consequence | A typo in `expect` would otherwise surface only after a live search had been paid for. |
| `run_e2e` builds each turn with `build_initial_orchestrator_state` instead of hand-writing a non-empty check and a `HumanMessage`. | correction, no vote | That helper is what `api.py:318` uses to start a turn, and `run_expert` already uses the matching `build_initial_pipeline_state`. It normalizes whitespace and rejects an empty query. |
| The multi-case guards and their regression test stay as v1 had them. | D3 (option A) | The guards are correct today only because a Phoenix dataset happens to hold one example, which stops being guaranteed once datasets are keyed by kind. Rejected alternative: a loader assertion of one case per kind, which walks back commit 45ef329's move to a shape allowing several cases per agent. |
| The prompt extraction and its `sys.path` insert stay as v1 had them. | D4 | Verified empirically. The insert belongs in the test's file-location loader, not at the runner's module scope, where it would run on every real invocation to serve only the test. |
| `report` keeps dropping `route_correct`. | D5 | Confirmed and closed. `run_report` raises unless the turn paused, and the orchestrator's only `interrupt()` is the reporter gate, so pausing implies the destination was `report`. The guard is strictly stronger than the judge; a zero is unreachable. |
| `DESTINATIONS` becomes a module constant. | correction, no vote | The same literal set is needed by `thread_output` and by `run_e2e`'s `expect` validation. `CLAUDE.md` requires module constants at the top of the file. |
| Task 5 states the new `experiment_name` and `case_count`. | correction, no vote | v1 left both unspecified when the loop moved from cases to kinds. |

**Accepted risks carried from the review.**

- On an `e2e` setup-turn misroute the task errors, so Phoenix records no scores
  at all for that kind rather than a zero beside the other judges. This is the
  cost of D1 option B and was accepted knowingly.
- The multiplication and the loop introduced by D3 have no caller today, and a
  dozen-line regression test ships for a shape nothing currently uses.
- **`e2e` cannot run `groundedness`.** The orchestrator's `expert` node discards
  the expert's sources and returns only an `AIMessage`
  (`app/src/agents/orchestrator/nodes/expert.py`), and `OrchestratorState` has no
  key for them. Surfacing them would be an application-code change, which this
  plan puts out of scope. After `expert-taiwan-strait-v1` is deleted, the suite's
  entire citation-grounding signal rests on the niger case, which has only ever
  passed.

No recommendation was rejected. No choice remains open.

## Scope and non-goals

`app/tests/manual_quality/cases.json` becomes an object keyed by kind instead of
a flat list of cases tagged with an `agent` field. There are four kinds, one case
each, all happy paths. The runner moves from one dataset and one experiment per
case to one per kind, extracts its four rubric prompts to a sibling module, and
replaces three near-identical evaluator builders with one judge table.

| Kind | Case | Input shape | Task | Judges |
|---|---|---|---|---|
| `expert` | `expert-niger-coup-v1` | `query` | `run_expert` | groundedness, usefulness |
| `orchestrator` | `orchestrator-dune-follow-up-v1` | `messages` | `run_orchestrator` | route_correct, rewrite_quality |
| `report` | `report-vilnius-summit-v1` | `messages` + `resume_actions` | `run_report` | report_fidelity |
| `e2e` | `e2e-finland-sweden-v1` | `turns` | `run_e2e` | route_correct, rewrite_quality, usefulness |

**Not in scope.** No application code under `app/src/` changes. No sad-path cases
are added. The judge model, `JUDGED_SCORE_THRESHOLD`, `PHOENIX_TIMEOUT_SECONDS`,
the paywalled-domain fetch failures, and `.github/workflows/evals.yml` are all
untouched. `CLAUDE.md` never documents this schema and needs no update.

## Deviation from the brainstorm, with the reason

The brainstorm's Q9 settled on the canonical Phoenix shape and recorded that
`evaluate_experiment` disappears, with judges passed inline to `run_experiment`.
**The per-kind granularity is implemented; the single merged call is not.**

Verified against arize-phoenix-client 3.3.0,
`phoenix/client/resources/experiments/__init__.py`: when `run_experiment`
receives `evaluators`, it calls `evaluate_experiment` internally and forwards its
own `retries` and `timeout` verbatim. One value governs both the task executor
and the judge executor.

The current code deliberately splits them, and both halves are load-bearing:

- `retries=0` on the task, because a retried task run spends real Brave and
  OpenAI credit, and `CLAUDE.md` makes expert search, source, and model failures
  hard errors with no degraded fallback.
- `retries=3` on the judges, the Phoenix default, because the judge is a
  free-tier OpenRouter endpoint. This is not theoretical: the 2026-09-10 run had
  a groundedness call exceed the 180 second timeout, get cancelled and requeued,
  and succeed on retry. Under a merged call with `retries=0` that run would have
  reported a judge error indistinguishable from a quality regression.

So the two calls stay, with their differing `retries`. Q9's decided value was the
granularity, which this plan delivers. One consequence: the existing assertion in
`test_live_results_use_phoenix_native_output` about a single `evaluate_experiment`
call carrying `print_summary=True` **survives unchanged**, contrary to the flag
recorded in the brainstorm.

## File responsibilities

| File | Responsibility |
|---|---|
| `app/tests/manual_quality/judge_prompts.py` | New. The four rubric prompt constants and nothing else. |
| `app/tests/manual_quality/cases.json` | Rewritten. Four kinds, one case each, judge-prefixed reference keys. |
| `app/tests/manual_quality/basic_agent_evaluation.py` | Loader, task functions, judge table, kind table, and the per-kind experiment loop. |
| `app/tests/unit_tests/test_manual_quality_evaluation.py` | Loader validation, the shipped-file check, `route_correct`, `thread_output`, and the `run_e2e` turn loop. |

## Ordered tasks

### Task 1 — Extract the rubric prompts

Create `app/tests/manual_quality/judge_prompts.py` holding
`GROUNDEDNESS_PROMPT`, `USEFULNESS_PROMPT`, `REWRITE_QUALITY_PROMPT`, and
`REPORT_FIDELITY_PROMPT`, moved verbatim. Import them in the runner:

```python
from judge_prompts import (
    GROUNDEDNESS_PROMPT,
    REPORT_FIDELITY_PROMPT,
    REWRITE_QUALITY_PROMPT,
    USEFULNESS_PROMPT,
)
```

Verified: `app/src` is on `sys.path` through the editable install's
`__editable__.agent-0.0.1.pth`, which is why `from config import ...` resolves.
`tests/manual_quality/` is not. The runner reaches its own directory only
because Python puts a script's directory on `sys.path[0]`, and both the local
command and the CI command (`.github/workflows/evals.yml:36`) run it as a script.

The unit test does not. It loads the runner through
`importlib.util.spec_from_file_location`, which sets `__file__` but adds nothing
to `sys.path`, so a flat `from judge_prompts import ...` raises
`ModuleNotFoundError` under pytest. `_load_runner` must insert
`str(RUNNER_PATH.parent)` into `sys.path` before `exec_module`. Do this in
Task 1 or all nine existing loader tests fail.

The insert belongs in the test loader, not at the runner's module scope. The
runner's normal execution already resolves the import through `sys.path[0]`, and
a module-scope insert would run on every real invocation to serve only the test.

Pure move, no text changes. Validate:

```
cd app && .venv/bin/python -m pytest tests/unit_tests/test_manual_quality_evaluation.py -q
cd app && .venv/bin/python tests/manual_quality/basic_agent_evaluation.py --validate-cases
```

### Task 2 — The judge table and the kind table

Replace `build_expert_evaluators`, `build_orchestrator_evaluators`,
`build_reporter_evaluators`, and `build_agent_run_info` with two functions. Both
are functions rather than module constants so they may name the dataclasses and
task functions defined above them, which is the pattern `build_agent_run_info`
already uses.

Add one module constant beside the existing ones, at the top of the file per
`CLAUDE.md`. It is needed by both `thread_output` and `run_e2e`:

```python
DESTINATIONS = {"geopolitical", "other", "report"}
```

```python
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
```

`route_correct` changes the reference key it reads:

```python
@create_evaluator(kind="CODE", name="route_correct")
def route_correct(output: Any, reference: dict[str, Any]) -> bool:
    """Require the completed graph to choose the case's expected branch."""
    if not isinstance(output, dict):
        raise RuntimeError("Task produced no output")
    return bool(output.get("destination") == reference["route_correct_destination"])
```

`KNOWN_AGENTS` is deleted. Its comment about `"reporter"` being servable from
commit 5a goes with it, which is the narrow exception to leaving comments alone.
`JUDGED_EVALUATORS` stays as is; all four judged names are unchanged.

Validate: `.venv/bin/python -m mypy --strict tests/manual_quality` and
`-m ruff check .`

### Task 3 — The new case file and the nested loader

Rewrite `cases.json`. The niger and vilnius bodies are carried over verbatim
except for the renamed reference keys; the dune and finland-sweden cases are new.

Note the asymmetry inside `e2e.turns`: turn one carries `expect` and turn two
does not. That is deliberate and is explained in `run_e2e`'s docstring.

```json
{
  "expert": [
    {
      "id": "expert-niger-coup-v1",
      "input": {
        "query": "What has been the regional impact of the 2023 Niger coup on West African security cooperation, and how did ECOWAS's response unfold?"
      },
      "output": {
        "usefulness_required_points": [
          "How the coup collapsed ECOWAS-led security cooperation with Niger",
          "What sanctions and diplomatic pressure ECOWAS adopted and how they ended"
        ]
      },
      "metadata": { "case": "niger-coup", "version": 1 }
    }
  ],
  "orchestrator": [
    {
      "id": "orchestrator-dune-follow-up-v1",
      "input": {
        "messages": [
          { "role": "user", "content": "Who wrote the novel Dune?" },
          { "role": "assistant", "content": "Dune was written by Frank Herbert and published in 1965." },
          { "role": "user", "content": "When did he die?" }
        ]
      },
      "output": {
        "route_correct_destination": "other",
        "rewrite_quality_intent": "When Frank Herbert, the author of Dune, died"
      },
      "metadata": { "case": "dune-follow-up", "version": 1 }
    }
  ],
  "report": [
    {
      "id": "report-vilnius-summit-v1",
      "input": {
        "messages": [
          { "role": "user", "content": "What did NATO's 2023 Vilnius summit decide about Ukraine's membership path?" },
          { "role": "assistant", "content": "The 2023 Vilnius communiqué dropped the MAP requirement and extended an invitation to Ukraine 'when allies agree and conditions are met' — see [BBC](https://www.bbc.com/news/world-europe-66139629) and [Reuters](https://www.reuters.com/world/europe/nato-leaders-summit-2023-07-12/). The allies also removed the requirement for a Membership Action Plan from Ukraine's path." },
          { "role": "user", "content": "Write me a report on what the Vilnius summit decided about Ukraine's membership and what the allies' conditions were." }
        ],
        "resume_actions": [ { "action": "approve" } ]
      },
      "output": {
        "report_fidelity_outline": "What the 2023 Vilnius summit decided about Ukraine's membership path and which conditions the allies attached, drawn only from the conversation's researched material"
      },
      "metadata": { "case": "vilnius-summit-report", "version": 1 }
    }
  ],
  "e2e": [
    {
      "id": "e2e-finland-sweden-v1",
      "input": {
        "turns": [
          {
            "query": "Why did Finland abandon military non-alignment after Russia's full-scale invasion of Ukraine, and why did it become a NATO member in April 2023?",
            "expect": "geopolitical"
          },
          { "query": "What about Sweden?" }
        ]
      },
      "output": {
        "route_correct_destination": "geopolitical",
        "rewrite_quality_intent": "Why Sweden pursued NATO membership after Russia's full-scale invasion and what happened with its accession",
        "usefulness_required_points": [
          "Why Sweden applied for NATO membership after Russia's full-scale invasion",
          "What delayed Sweden's accession and when it completed"
        ]
      },
      "metadata": { "case": "finland-sweden-e2e", "version": 1 }
    }
  ]
}
```

Rewrite the loader. `CASE_FIELDS` loses `agent`; `KNOWN_AGENTS` is gone.

```python
CASE_FIELDS = {"id", "input", "output", "metadata"}


def load_cases() -> dict[str, list[dict[str, Any]]]:
    """Load the per-kind case lists and reject accidental schema drift."""
    raw: object = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("cases.json must contain a non-empty object keyed by kind")

    cases = cast(dict[str, list[dict[str, Any]]], raw)
    kinds = build_kinds()
    specs = judge_specs()
    if set(cases) != set(kinds):
        raise ValueError(f"cases.json must hold exactly the kinds {sorted(kinds)}")

    seen: set[str] = set()
    for kind_name, kind_cases in cases.items():
        if not isinstance(kind_cases, list) or not kind_cases:
            raise ValueError(f"{kind_name} must hold a non-empty list of cases")
        # Judges belong to the kind, so every case under it must carry every
        # reference key those judges read. Without this the run fails deep
        # inside Phoenix's field mapping, per case, after the task has already
        # spent live API credit.
        required = {
            specs[judge].reference_key
            for judge in kinds[kind_name].judges
            if specs[judge].reference_key is not None
        }
        for case in kind_cases:
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
                    f"{case['id']} is missing {missing} required by kind {kind_name}"
                )
    return cases
```

The loader deliberately does not validate the shape of `input`. That stays
per-kind, inside each task, so the generic loader does not learn one kind's turn
schema. `run_e2e` compensates by validating its whole script before its first
graph call, so a malformed script still costs nothing.

Validate: `.venv/bin/python tests/manual_quality/basic_agent_evaluation.py --validate-cases`

### Task 4 — Task functions

Add one shared helper so the three thread-driving tasks stop repeating their
validation, and so every judge needs one field mapping rather than one per kind.

```python
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
```

`load_cases` calls `build_kinds()`, which only *names* the task functions and
never calls them, so `--validate-cases` stays free of network, environment, and
agent imports exactly as it is today.

`run_expert` gains one field so `groundedness` and `usefulness` can map
`question` to `output.standalone_query` for every kind:

```python
    return {
        "standalone_query": query,
        "answer": answer,
        "sources": [...unchanged...],
    }
```

`run_orchestrator` ends with `return thread_output(result)`. `run_reporter_thread`
is renamed `run_report`, keeps its pause guard and its docstring, and also ends
with `return thread_output(result)` instead of `{"report": report}`.

`run_e2e` is new:

```python
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
```

**Behaviour change to record.** `run_orchestrator` previously raised when the
destination was outside `{"geopolitical", "other"}`. `thread_output` accepts
`"report"` too, because it is shared with `run_report` and `run_e2e`.

What happens on an orchestrator misroute to `report` depends on the history, and
neither path is silent. When the thread has no researched link,
`has_researched_material` is false, the reporter node short-circuits with a
refusal message, and `route_correct` scores 0. That is the shipped dune case.
When the thread does have a researched link, the reporter subgraph reaches
`gate`, `interrupt()` raises `GraphInterrupt`, and because `run_orchestrator`
uses the module-level graph compiled with no checkpointer, that propagates out
of `ainvoke` and fails the task loudly. Verified in
`langgraph/types.py:403,415`.

Validate: the new turn-loop unit tests from the Test section, plus mypy and ruff.

### Task 5 — One experiment per kind

`run_experiment_case` becomes `run_kind`. The two Phoenix calls and their
differing `retries` are preserved exactly as today; only the granularity and the
example payload change.

```python
    dataset = await client.datasets.create_dataset(
        name=f"geopoliticai-{kind_name}",
        # Phoenix reads only input, output and metadata from an example. `id`
        # is this runner's own and stays out of the payload.
        examples=[
            {field: case[field] for field in ("input", "output", "metadata")}
            for case in kind_cases
        ],
        dataset_description="Manual advisory quality smoke cases",
        timeout=PHOENIX_TIMEOUT_SECONDS,
    )
```

The experiment name and the recorded case count follow the same move from case to
kind: `experiment_name=f"{kind_name}-{timestamp}"`, and `experiment_metadata`
carries `"case_count": len(kind_cases)` rather than the suite-wide total.

Two existing guards are hardcoded to exactly one case and must be **replaced**,
not kept. Both work today only because every kind ships one case, and both break
the moment anyone uses the extensibility the `Kind` docstring promises.

`validate_evaluations` at `basic_agent_evaluation.py:465` counts against the
number of judges, but `matching` spans every case in the kind's experiment, so
for N cases it legitimately holds `N * len(expected_names)` entries:

```python
    # Was `len(matching) != len(expected_names)`, which is true for any kind
    # holding more than one case.
    expected_total = len(kind_cases) * len(expected_names)
    if actual_names != expected_names or len(matching) != expected_total:
        raise RuntimeError(
            f"Expected {expected_total} evaluations for {kind_name} "
            f"({sorted(expected_names)} over {len(kind_cases)} cases), "
            f"got {len(matching)} named {sorted(actual_names)}"
        )
```

`run_kind`'s task-run guard at `basic_agent_evaluation.py:555` has the same
shape, and additionally inspects only `task_runs[0]`, so a failure in any later
case would pass unnoticed:

```python
    task_runs = task_result["task_runs"]
    if len(task_runs) != len(kind_cases):
        raise RuntimeError(
            f"Expected {len(kind_cases)} task runs for {kind_name}, got {len(task_runs)}"
        )
    for task_run in task_runs:
        if task_run.get("error"):
            raise RuntimeError(f"Invalid task run: {task_run}")
        if not isinstance(task_run.get("output"), dict):
            raise RuntimeError("Task run produced no structured output")
```

`CaseOutcome.case_id` becomes `kind_id`, carrying the kind name. A failing score
is reported as `kind/judge=score`.

The `explanation_names` parameter is deleted. It exists to say which judges must
return an explanation, and that is exactly the judged ones, so
`set(kind.judges) & JUDGED_EVALUATORS` derives it. One fewer field in the kind
table and one fewer argument to thread through.

Dataset names change from `geopoliticai-<case-id>` to `geopoliticai-<kind>`. The
four old per-case datasets stay in Phoenix as orphans with their history intact.
Nothing reads them and nothing breaks; delete them by hand if they clutter the
list.

```python
# ponytail: failures are reported per kind, not per case. Every kind holds one
# case today. An evaluation run carries `experiment_run_id`, not a dataset
# example id, so naming the individual case inside a multi-case kind means
# joining through `task_runs[*]["dataset_example_id"]`. Add that join when a
# kind actually grows a second case.
```

`main` loops `build_kinds()` and passes `cases[name]`.

Validate, live, with `.env` loaded and Phoenix running:

```
cd app && .venv/bin/python tests/manual_quality/basic_agent_evaluation.py
```

Expect four dataset uploads, four experiment links, and three live searches, one
for the expert and two for `e2e` finland. `orchestrator` and `report` make none.

## Test and follow-up notes

**Rewritten.** Every `load_cases` test moves from flat-list fixtures to nested
ones. `test_load_cases_rejects_a_json_object` inverts into
`test_load_cases_rejects_a_json_list`. `test_load_cases_rejects_an_unknown_agent`
becomes an unknown kind key. `test_load_cases_accepts_the_real_shipped_cases_json`
asserts the four new ids and the four kind keys.

**New.**

- A case whose `output` omits a reference key its kind's judges read raises,
  naming both the case id and the missing key. Cover `report` missing
  `report_fidelity_outline` and `e2e` missing `rewrite_quality_intent`.
- A duplicate id across two different kinds raises.
- `route_correct` reads `route_correct_destination`, both the passing and the
  failing direction.
- `run_e2e` against a stub graph exposing only `ainvoke`. No network, no
  application graph.
  - A `query` turn sends the state `build_initial_orchestrator_state` produces,
    and a `resume` turn sends a `Command`.
  - A resume with no pending `__interrupt__` raises.
  - A turn carrying neither key, or both `resume` and `expect`, raises.
  - An empty or non-string query raises, through
    `build_initial_orchestrator_state`.
  - **A setup turn whose destination differs from its `expect` raises**, and the
    message names both the actual and the expected branch. This is the
    regression guard for D1.
  - **A script carrying an unknown `expect` value raises before the stub graph
    is invoked at all.** Assert the stub recorded zero calls. This is what makes
    a typo free rather than paid for.
- `thread_output` excludes the final AI message from `conversation`. Feed it a
  four-message thread whose last message is a distinctive report string, and
  assert that string is absent from `conversation` while an earlier research
  citation is still present. This is the regression guard for the judge
  contamination the correctness review caught.
- `validate_evaluations` accepts a kind holding two cases. Build a fake result
  with two cases' worth of evaluation runs and assert it does not raise. This
  fails against the current `len(matching) != len(expected_names)` check. The
  stub is cheap because `_load_runner()` is typed `Any`, so `mypy --strict` does
  not inspect the argument.

**Unchanged.** `test_live_results_use_phoenix_native_output` keeps its single
`evaluate_experiment` assertion, per the deviation recorded above. Its
`"orchestrator experiment:"` string assertions still hold.

**Follow-up, not in this plan.**

- Record the `expert-taiwan-strait-v1` citation-misattribution defect somewhere
  durable before that case is deleted. It scored `groundedness` 2.0 while
  scoring `usefulness` 5.0 on the same answer. The sweden rewrite defect
  survives inside `e2e` finland turn two.
- After that deletion the suite's entire citation-grounding signal is the niger
  case, which has only ever passed. `e2e` cannot help: the orchestrator's
  `expert` node discards the expert's sources, and giving `OrchestratorState` a
  key for them is an application-code change this plan excludes.
- Nothing in the suite tests the reporter against research the expert actually
  produced. Accepted in the brainstorm at Q13.
- `JUDGED_SCORE_THRESHOLD` remains 3.0 and provisional.
- The judge timeout and the paywalled-domain fetch failures are untouched.

## Correctness review findings and their disposition

A correctness review read the source and the installed Phoenix and langgraph
rather than this plan's claims. All five findings were reproduced and accepted.

1. **Accepted, high.** Unifying the three thread tasks on `thread_output` fed
   `report_fidelity` a conversation that already contained the report it was
   judging, making "stays within the research supplied" close to tautological.
   Today's code avoids this by mapping `conversation` to `input.messages`.
   Reproduced: `build_transcript(messages)` contains the report, and
   `build_transcript(messages[:-1])` does not while keeping the research.
   Fixed by trimming the final message in `thread_output`.
2. **Accepted, high.** The new per-kind count assertion was unreachable. The
   untouched check above it uses `len(matching) != len(expected_names)`, which
   raises for any kind holding more than one case, so the guard written for
   exactly that case never ran. Fixed by replacing the old check rather than
   adding beside it.
3. **Accepted, medium.** `run_kind`'s task-run guard requires exactly one run
   and inspects only `task_runs[0]`, so a failure in any later case of a
   multi-case kind would pass unnoticed. Fixed by counting against
   `len(kind_cases)` and looping.
4. **Accepted, medium.** Same root cause as finding 1. `rewrite_quality`'s
   history would have included the answer to the very rewrite it was grading.
   The `messages[:-1]` trim fixes both.
5. **Accepted, low.** The plan claimed an orchestrator misroute to `report` is
   caught by `route_correct` scoring 0. That holds only when the thread carries
   no researched link, which is true of the shipped dune case but not in
   general. With research present the reporter subgraph reaches `gate`, and
   `interrupt()` raises `GraphInterrupt` out of a graph with no checkpointer.
   Verified at `langgraph/types.py:403,415`.

Findings 1 and 4 are the reason two regression tests exist: one asserting the
final message is absent from `conversation`, one asserting a two-case kind
validates.

## Open questions

None. Every decision raised in the plan review was answered; see the Review
changes table above and the review record for the reasoning behind each.

---

**Readiness:** Ready for implementation
**User approval:** Awaiting approval
