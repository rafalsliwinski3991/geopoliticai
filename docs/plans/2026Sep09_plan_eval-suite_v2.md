# Plan — Edge-case eval suite with an OpenRouter judge

Implements the eval half of
`docs/brainstorming/2026Sep09_brainstorm_v2_tests-and-openrouter-evals.md`.
Depth: **full**. It changes the judge provider, adds a required environment
variable and repository secrets, adds a GitHub Actions workflow, rewrites the
case schema, and changes the three guidance files. Seven ordered commits
(commit 5 is split into 5a and 5b, because 5b needs case data only the user can
supply).

**Shape: trimmed.** After review, the user chose the trimmed shape over the
plan's original scope. The four deterministic edge cases are dropped, and the
judge swap is ordered ahead of the rubric rewrite so each can be measured
separately. See "Shape decision" near the end for the evidence and what was
given up.

The unit-test half is `docs/plans/2026Sep09_plan_unit-test-layout_v1.md`. The
two plans share no files.

## Changelog (v1 → v2)

Every entry names the finding that drove it. Findings that were surfaced and
rejected are listed too, with the reason, so nothing a reviewer raised is
silently dropped.

### Accepted and applied

| # | Change | Driven by | Why |
| --- | --- | --- | --- |
| 1 | Commit 6 now edits **`AGENTS.md` and `.github/copilot-instructions.md` as well as `CLAUDE.md`** | guidance-lens HIGH #1 | All three files are byte-identical apart from their H1 (verified by `diff`), all three carry the same "update this file for application-codebase changes" rule, and the last five commits touching any of them touched all three. Updating only `CLAUDE.md` would let them diverge for the first time. |
| 2 | Commit 6 **rewords** the "advisory and not part of pytest or CI" sentence rather than preserving it | guidance-lens MEDIUM #2 | v1 claimed the sentence stays true. Once `.github/workflows/evals.yml` exists and runs that script, "not part of CI" is false. "Dispatch-only and gates nothing" is the claim that is actually true. |
| 3 | `run_reporter_thread` gains a **hard `__interrupt__` guard** before it resumes anything | framework-lens HIGH, correctness-lens HIGH #3 | Both lenses found it independently. See finding 4 below for the mechanism correction. |
| 4 | The guard's rationale is **"silent no-op", not "opaque crash"** | lead adjudication of a lens conflict | `correctness-lens` claimed `Command(resume=...)` on a thread with no pending interrupt raises `EmptyInputError`. The lead ran langgraph 1.0.1 directly: it returns the completed state unchanged and raises nothing. `framework-lens` was right. The failure mode is worse than either lens's fix assumed, so the guard is mandatory rather than merely tidy. |
| 5 | Commit 5a now spells out **`build_reporter_evaluators`** in full, with its `ClassificationEvaluator` and `bind_evaluator` mapping | framework-lens MEDIUM, correctness-lens LOW, supplied feedback #1 | `remap_eval_input` raises `ValueError: Missing required field` for an unmapped template variable, and v1 left this one evaluator as the only unwritten binding in the plan. |
| 6 | `REPORT_FIDELITY_PROMPT` gains a **`{conversation}` variable**, mapped to `input.messages` | supplied feedback #1 | The rubric asks the judge whether the report "stays within the research supplied in the conversation" while v1's template interpolated only `{outline_intent}` and `{report}`. The judge could not have answered its own question. |
| 7 | Commit 3 and commit 5b now state **per-case `dataset_name` and `experiment_name` derivation from `case["id"]`** | correctness-lens HIGH #1, framework-lens LOW | Three expert cases keyed on `case["agent"]` would pile up as three versions of one dataset and share one experiment name, erasing the per-case identity a reviewer reads Phoenix for. |
| 8 | The `route_correct` regression test is **explicitly assigned to commit 5a**, not commit 3 | correctness-lens HIGH #2 | The chained-comparison fix lands in commit 5a. A test for it written in commit 3 would fail through commits 3 and 4, breaking the plan's own "every commit leaves `make test` green" invariant. |
| 9 | Commit 4 **still raises on a CODE evaluator's `run.error`**; only judged evaluators have their errors counted | correctness-lens MEDIUM | A `KeyError` in `route_correct` is a bug in this repo, not a flaky free-tier judge. Downgrading it to a counted "judge error" would hide a real defect behind an OpenRouter-hiccup-shaped statistic. The rule keys on the `JUDGED_EVALUATORS` set that already exists for the threshold rule, so it costs one condition. |
| 10 | `evaluate_experiment` **drops its explicit `retries=0`** and inherits Phoenix's default of 3 | supplied feedback #3, framework-lens MEDIUM | Verified: `AsyncExperiments.evaluate_experiment` defaults to `retries=3`. A free-tier OpenRouter 429 currently becomes a permanent judge error indistinguishable from a quality regression. `run_experiment` keeps `retries=0`, because retrying a task run spends real Brave and OpenAI credit. This is a deletion, not an addition. |
| 11 | `require_env_value` is **deleted from the plan entirely** | lead, applying the repo's "reuse before writing" principle | `require_env` already rejects an unset or empty variable, and `main` already calls it before the judge is built. `os.environ["OPENROUTER_API_KEY"]` is then safe. One fewer helper and one fewer unit test. |
| 12 | Commit 4 adds a **module-level `logger = logging.getLogger("agent")`** | lead, reading the source; corrected by codex-critic HIGH #1 | v1's code block called `logger.error(...)` but the runner imports no `logging` and defines no logger. The lead first proposed `logger = init_environment()` inside `main`; the critic showed that `validate_evaluations` is module-level and would raise `NameError` on the first judged-evaluator error. The module-level name resolves to the same object `init_environment()` returns and configures. |
| 13 | The reporter case's data now carries a **stated `has_researched_material` requirement** | correctness-lens HIGH #3 (second gate), lead | `agents/reporter/state.py:95-120` requires an assistant turn containing a markdown link to `http(s)` before the reporter subgraph is invoked at all. v1 left the case's messages entirely to the user with no mention of this. |
| 14 | Commit 4 now notes that **a mis-mapped evaluator surfaces as a counted judge error** | lead, from testing `bind_evaluator` | `bind_evaluator` accepts a mapping with missing or extra keys without complaint; the failure is deferred to evaluation time and caught by Phoenix. Under commit 4's new semantics that looks like a throttled judge. The first live run of any new evaluator must therefore show zero judge errors before its "recorded, not fatal" behaviour is trusted. |
| 15 | A rule added: **no rubric template may contain a literal `{` or `}`** | supplied feedback #2, narrowed | See rejection 1 for why the feedback's broader recommendation was not taken. |
| 16 | Open questions record that **reasoning is disabled with `extra_body`**, a `ClassificationEvaluator` kwarg | supplied feedback #4 | Verified: `LLMEvaluator.__init__` ends `self.invocation_parameters = kwargs`, the same path `temperature=0` already travels. Documentation only, no code until measurement says it matters. |
| 17 | Commit 4's prose corrected: **`experiment_metadata` carries static run parameters**, outcome totals live in `CaseOutcome` | supplied feedback #6 | `run_experiment` is called before `evaluate_experiment`, and Phoenix exposes no way to mutate experiment metadata afterwards. v1's prose implied otherwise. |
| 18 | Naming drift fixed: every mention is now **`JUDGED_SCORE_THRESHOLD`** | correctness-lens LOW | v1 called it `SCORE_THRESHOLD` twice in prose. |
| 19 | Line-number citations corrected: `JUDGE_MODEL` is at **`:27`**, `CASE_NAMES`/`CASE_FIELDS` at **`:25-26`**, and the boundary-test assertions at **`test_manual_quality_evaluation.py:42-48`** | scout staleness | v1 cited `:26`, `:24-25`, and `test_manual_quality_evaluation.py:32` — the last pointing at unrelated code inside a list comprehension rather than at the assertions it claimed. Every other cited line number in v1, including the deep Phoenix-internal ones, was independently verified against the installed venv and is correct. |
| 20 | `validate_evaluations`'s loop is now **written out whole**, with `judge_errors` and `failed` initialised and the `continue`'s meaning stated | codex-critic HIGH #1 | The fragment alone never showed where the counters lived, leaving the implementer to guess. |
| 21 | `CaseOutcome.below_threshold` renamed **`failed`**, and it now collects a falsy CODE score as well as a sub-threshold judged score | codex-critic MEDIUM #1 | The plan declared "CODE evaluators fail on a falsy score" but the only collection was of judged evaluators, and `main` exits on that list. A misrouted orchestrator case — `route_correct` returning `False`, recorded as a valid 0.0 — would have exited green. That is the exact regression `route_correct` exists to catch. |
| 22 | **Commit 5 split into 5a (code) and 5b (case data)** | codex-critic HIGH #2 | v1 and the first draft of v2 both made commit 5 unstartable: it required four cases the plan forbids the implementer from inventing, with no stated checkpoint. The split lets the rubric generalisation, the reporter machinery and the `route_correct` fix land immediately, and isolates the editorial work behind its own gate. |
| 23 | `"reporter"` moves out of commit 3's `KNOWN_AGENTS` into **commit 5a** | codex-critic MEDIUM #2 | Commit 3 would otherwise accept a case naming an agent its dispatch table could not route, failing at lookup instead of at load. |
| 24 | Validation wording fixed: **judged** evaluators return an explanation, `route_correct` does not | codex-critic MEDIUM #3 | Both v1 and the first v2 draft demanded "every evaluator producing a score and an explanation", an acceptance gate a CODE evaluator can never pass. |
| 25 | Commit 6 is **explicitly gated on Phoenix Cloud being confirmed reachable first**, and the "local-only fallback" is restated as "commit 6 is not landed" | codex-critic MEDIUM #4 | The workflow passes `PHOENIX_COLLECTOR_ENDPOINT` from a secret and `require_env` hard-fails without it, so there is no in-workflow fallback. Calling it one was wrong. |

### Surfaced and rejected

1. **"Switch every rubric to mustache `{{var}}` syntax and wrap the data in
   `[BEGIN DATA]` / `[END DATA]` delimiters."** (Supplied feedback #2.)
   Rejected on measurement. The stated reason was that a report or source text
   containing a literal `{` would be parsed as an unbound template variable.
   That is false: `PromptTemplate` parses the template **once at construction**
   and substitutes values afterwards, so
   `PromptTemplate('Answer:\n{answer}\n').render({'answer': 'JSON {"a": 1} and {curly}'})`
   renders correctly. The real hazard is a literal brace **in the template text
   itself**, which none of these rubrics has. Rewriting four working rubrics
   into a second syntax to defend against a hazard that does not exist is churn.
   The actual guard is item 15's one-line rule. The `[BEGIN DATA]` delimiters
   were rejected separately: these rubrics already label every interpolated
   block (`Question:`, `Answer:`, `Sources:`), which is the same separation in
   fewer characters.

2. **"Wrap `evaluate_experiment` in `with suppress_tracing():`."** (Supplied
   feedback #5.) Rejected on two independent grounds. First, the import does not
   exist here: `from phoenix.trace import suppress_tracing` raises
   `ModuleNotFoundError`, because the full `arize-phoenix` package is not
   installed — only `arize-phoenix-client`, `-evals` and `-otel`. The working
   import is `phoenix.otel.suppress_tracing`. Second, and decisively, it would
   delete telemetry this repo wants. `phoenix/evals/llm/wrapper.py` decorates
   its generation methods with `@trace`, and Phoenix's experiments runner wraps
   evaluator execution in `capture_spans(resource)`
   (`phoenix/client/resources/experiments/__init__.py:137-150`, entered at
   `:1989`) specifically to attach judge spans to the experiment. The tutorial
   that motivated the suggestion uses `suppress_tracing` around
   `async_evaluate_dataframe`, which has no such capture. Suppressing here would
   throw away the judge spans Phoenix is deliberately collecting.

3. **"Add an automated regression test for `run_reporter_thread`'s resume
   loop."** (guidance-lens LOW/MEDIUM #3.) Rejected as already covered. The
   exact mechanism — `build_graph(checkpointer=InMemorySaver())` driven with
   `Command(resume={"action": "approve"})` — is regression-tested at
   `tests/integration_tests/test_orchestrator_graph.py:396`, `:429` and `:458`,
   and the reporter child's own equivalents at
   `tests/integration_tests/test_reporter_graph.py:100-169`.
   `run_reporter_thread` is thin glue over a mechanism with existing coverage.
   The lens's underlying concern — that new non-trivial control flow needs a
   check that fails when it breaks, per working principle 5 — is met instead by
   item 3's `__interrupt__` guard, which is itself the runnable check: it fails
   loudly on exactly the regression the lens was worried about.

## Scope summary

**Rewritten.** `app/tests/manual_quality/basic_agent_evaluation.py` keeps its
shape as a standalone script with one `evaluate_experiment` call site, and
changes in four ways: the judge becomes a pinned OpenRouter free model, the
Phoenix destination becomes configurable, cases come from a list rather than
two named keys, and judge failures are recorded rather than fatal.

**Rewritten.** `app/tests/manual_quality/cases.json` becomes a list of entries,
each naming the agent it runs against. It grows from 2 judged cases to 6, all
of them cases where a judge can see something an `assert` cannot.

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
`CASE_FIELDS`, the `run.error` raise for judged evaluators inside
`validate_evaluations`, and the explicit `retries=0` on `evaluate_experiment`.
`phoenix_base_url()` is **kept** unchanged: its `/v1/traces` suffix stripping
works for a Phoenix Cloud endpoint exactly as it does for the Compose one.

**Not added.** A `require_env_value` helper. `require_env` already rejects an
unset or empty variable and `main` already calls it before the judge is built,
so `os.environ["OPENROUTER_API_KEY"]` needs no wrapper.

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

### Findings where the code contradicts the brainstorm

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
   `test_api.py:488`. **Dropped from the eval case list.** The trim later
   removed the other four deterministic paths as well, so this finding is now
   historical: it explains why truncation was never a candidate even under the
   original scope.

2. **The reporter case needs a checkpointer that the current runner does not
   build.** The brainstorm assumes reporter cases can run like the existing
   orchestrator case, which calls the module-level
   `agents.orchestrator.graph.graph`. That object is built by
   `graph = build_graph()` at `graph.py:59` with **no checkpointer**. Every
   reporter path pauses at `gate`, which calls `interrupt()`, and an interrupt
   cannot be resumed without a saver. Both `build_graph` functions already take
   a `checkpointer` argument documented as the hook for driving them with an
   `InMemorySaver` (`orchestrator/graph.py:19-28`,
   `reporter/graph.py:29-37`), and `langgraph.checkpoint.memory.InMemorySaver`
   is importable in this venv. **The reporter eval task builds its own graph
   with an `InMemorySaver`** rather than using the module-level one.

3. **Per-case judge failure recording needs no new machinery.** The brainstorm
   treats "record the failure per case and continue" as work. Phoenix already
   does it: the single-evaluation runner catches `BaseException` from an
   evaluator, records it on the span, and submits the evaluation with the error
   (`phoenix/client/resources/experiments/__init__.py:1994-2015`). The result
   surfaces as `run.error`, which the current `validate_evaluations` reads and
   **raises on**. The change is therefore a deletion plus a counter, not new
   error plumbing.

4. **Resuming a thread with no pending interrupt is silent, not loud.**
   Established by running langgraph 1.0.1 directly: a graph compiled with
   `InMemorySaver`, invoked to completion, then re-invoked with
   `Command(resume={"action": "approve"})` on the same `thread_id` returns the
   completed state unchanged and raises nothing. This is what makes commit 5a's
   `__interrupt__` guard mandatory rather than defensive: without it a misrouted
   reporter case scores a chat answer as a report and nothing anywhere reports
   a problem.

## File responsibilities

| File | Responsibility |
| --- | --- |
| `app/tests/manual_quality/basic_agent_evaluation.py` | The whole runner: case loading, per-agent tasks, evaluators, judge construction, Phoenix destination, threshold enforcement, process exit code. |
| `app/tests/manual_quality/cases.json` | Case data only. A list of entries, each naming its agent, input, expected output, and metadata. No behaviour. |
| `.github/workflows/evals.yml` | Dispatch-only trigger, secret injection, and nothing else. It runs the script and reports its exit code. |
| `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md` | The three guidance files, currently byte-identical apart from their H1. All three record the new environment variable, the workflow, and the judge provider, so the guidance stays true whichever agent reads it. |
| `app/tests/unit_tests/test_manual_quality_evaluation.py` | Guards the Phoenix-native output boundary, and gains the new loader and `route_correct` tests. |

## Ordered commits

Mechanical and isolated first, the case-schema rewrite in the middle, the new
live cases last. Every commit leaves the repo importable and `make test`
green. The one test that could break that invariant — the `route_correct`
regression test — is assigned to commit 5a, alongside the fix it tests.

Order: 1, 2, 3, 4, 5a, 5b, 6. Only 5b and 6 are gated on something outside the
implementer's control — 5b on the user's case content, 6 on Phoenix Cloud and
the repository secrets. Everything up to and including 5a can be written and
merged in one pass.

### Commit 1 — judge moves to OpenRouter

**Files.** `basic_agent_evaluation.py`.

**Safe here** because it changes one constant and one constructor call, and
touches no case data or control flow.

**Before** (`basic_agent_evaluation.py:27` and its use in `main` at `:377`):

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
    # `require_env` above has already rejected an unset or empty value, so the
    # direct read is safe and needs no wrapper of its own.
    judge = LLM(
        provider="openai",
        model=JUDGE_MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
    )
```

`LLM.__init__` forwards unknown keyword arguments to the underlying SDK client
constructor and documents `api_key` and `base_url` explicitly, so this needs no
new dependency. Verified by construction against the installed
`arize-phoenix-evals` 3.6.0: the model name is not validated and the async
client's base URL is set as passed.

Extend the existing `require_env` call in `main` to cover the new key:

```python
    require_env((*REQUIRED_ENV_VARS, "PHOENIX_COLLECTOR_ENDPOINT", "OPENROUTER_API_KEY"))
```

**Test.** `cd app && make lint && make test`, then a live local run of the two
**existing** cases against the **existing** rubrics.

This ordering is the point. The judge changes here and the ruler changes in
commit 5a, so this run measures the new judge against the scale the old judge
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

**Before** (`:376`):

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

Tracing needs **no** change at all. `phoenix.otel`'s span exporter, when
`register()` passes no explicit headers — and `tracing.py:init_tracing()` never
does — merges `get_env_phoenix_auth_header()`, which builds
`{"authorization": "Bearer <PHOENIX_API_KEY>"}` from `PHOENIX_API_KEY` alone
(`phoenix/otel/settings.py:351-366`, `phoenix/otel/otel.py:588-596`). The one
`PHOENIX_API_KEY` secret therefore authenticates both the REST client and the
OTLP exporter. No `PHOENIX_CLIENT_HEADERS`, no edit to `tracing.py`.

**Test.** `cd app && make lint && make test`, then one live local run to prove
the unset-key path is unchanged.

### Commit 3 — cases become a list

**Files.** `cases.json`, `basic_agent_evaluation.py`,
`tests/unit_tests/test_manual_quality_evaluation.py`.

**Safe here** because the two existing cases are carried across unchanged; only
their container and the loader change.

**Before** (`basic_agent_evaluation.py:25-26` and `load_cases`):

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
# `"reporter"` is added in commit 5b, with the task and evaluators that serve
# it. Accepting an agent name here that the dispatch table cannot yet route
# would let a valid-looking case pass the loader and then fail on lookup.
KNOWN_AGENTS = {"expert", "orchestrator"}

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
evaluator builders, and expected evaluation names.

**The dataset and experiment names must be derived from `case["id"]`, not from
`case["agent"]`.** This is the detail that makes a six-case list legible in
Phoenix. `create_dataset` with a reused name does not fail — the server treats
it as an update and stores a new version — so three expert cases keyed on the
agent would silently pile up as three versions of one dataset while their three
experiments shared a single name, erasing exactly the per-case identity a
reviewer opens Phoenix to read:

```python
        dataset_name=f"geopoliticai-{case['id']}",
        experiment_name=f"{case['id']}-{timestamp}",
```

The single `evaluate_experiment` call site inside `run_experiment_case` is
preserved, because `test_manual_quality_evaluation.py:42-48` asserts there is
exactly one and that it passes `print_summary=True`.

**New unit tests in this commit** (network-free, exercising the loader only):
`load_cases` rejects a JSON object, an empty list, an entry with a missing or
extra field, an unknown `agent` value, a blank `id`, and a duplicate `id`; and
`load_cases` accepts the real shipped `cases.json`, so the data file and its
schema check cannot drift apart. The `route_correct` test is **not** in this
commit — see commit 5a.

**Test.** `cd app && make lint && make test`, then a live local run of the two
carried-over cases producing the same evaluator names as before.

### Commit 4 — judge failures recorded, thresholds enforced

**Files.** `basic_agent_evaluation.py`.

**Safe here** because it changes only what the runner does with results it
already receives.

Phoenix catches evaluator exceptions per run and surfaces them as `run.error`.
The runner currently raises on the first one, at `:300`.

**Before** (`validate_evaluations`):

```python
    for run in matching:
        if run.error:
            raise RuntimeError(f"{run.name} failed: {run.error}")
```

**After.** `validate_evaluations` returns a tally instead of raising on a
*judged* evaluator's error, and the process decides at the end.

```python
# Two rules, not one number. Phoenix scores a bool evaluator as 0.0 or 1.0, so
# a *passing* CODE evaluator scores 1.0. A single threshold of 3.0 applied
# across both kinds would fail every run, including a perfect one.
JUDGED_SCORE_THRESHOLD = 3.0  # Provisional. No historical scores exist;
                              # revisit after the first runs.
JUDGED_EVALUATORS = {"groundedness", "usefulness", "rewrite_quality", "report_fidelity"}
# CODE evaluators fail on a falsy score, judged evaluators on < 3.0.


@dataclass(frozen=True)
class CaseOutcome:
    """What one case produced, so `main` can decide the exit code once."""

    case_id: str
    scored: int
    judge_errors: int
    failed: list[str]
```

The plumbing this needs: `validate_evaluations` gains a `case_id` parameter and
returns a `CaseOutcome` instead of `None`; `run_experiment_case` changes from
`-> None` to `-> CaseOutcome`, gains `case_id`, `case_count` and
`experiment_metadata` parameters, and returns what `validate_evaluations`
handed it; `main` accumulates the returned outcomes in a list. `dataclass` must
be added to the imports.

**`validate_evaluations` is module-level, so its logger must be too.** Add two
lines at module scope, next to the existing constants:

```python
import logging
...
logger = logging.getLogger("agent")
```

`main` already calls `init_environment()`, which runs `logging.basicConfig` and
returns `logging.getLogger("agent")` — the same object this module-level name
binds. Configuration therefore still happens exactly once, in `main`, before
anything logs. A `logger` local to `main` would raise `NameError` the first time
`validate_evaluations` tried to use it.

**A CODE evaluator's `run.error` still raises.** Only a judged evaluator's
error is counted. This is deliberate and the distinction matters: an exception
out of `route_correct` is a bug in this repository, and burying it in a
`judge_errors` tally would make it indistinguishable from an OpenRouter hiccup.
The rule keys on the `JUDGED_EVALUATORS` set that already exists for the
threshold rule, so it costs one condition.

Here is the whole loop, so the counters have a stated home and the `continue`
has a stated meaning — it skips only the structural checks below, which cannot
run on a run that produced no result:

```python
    judge_errors = 0
    failed: list[str] = []
    for run in matching:
        if run.error:
            if run.name not in JUDGED_EVALUATORS:
                raise RuntimeError(f"{run.name} failed: {run.error}")
            logger.error("%s: %s judge error: %s", case_id, run.name, run.error)
            judge_errors += 1
            continue
        ...  # the existing structural checks, unchanged
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
```

`validate_evaluations` otherwise keeps rejecting a *structurally* invalid
result, which is a bug in the runner rather than a flaky judge: a missing
evaluator name, a non-numeric score, a blank label, or a missing explanation
where one is required.

**Both evaluator kinds must be able to fail the run.** `failed` holds a judged
evaluator scoring below `JUDGED_SCORE_THRESHOLD` *and* a CODE evaluator scoring
falsy. Collecting only the judged ones would let a misrouted orchestrator case —
`route_correct` returning `False`, recorded by Phoenix as a valid score of 0.0 —
pass every check and exit zero, which is the exact regression `route_correct`
exists to catch.

**A wiring mistake looks like a flaky judge here, so read the first run
carefully.** `bind_evaluator` accepts an `input_mapping` with missing or extra
keys without complaint; the failure surfaces only at evaluation time, when
`remap_eval_input` raises `ValueError: Missing required field`, and Phoenix
catches it into `run.error`. Under the rule above that becomes a counted judge
error. The first live run of any new or re-mapped evaluator must therefore show
**zero** judge errors before the "recorded, not fatal" behaviour is trusted for
it.

`main` exits non-zero if any case has a judge error or a failed evaluator:

```python
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
```

**`experiment_metadata` records the run's static parameters, not its results.**
`run_experiment` is called before `evaluate_experiment`, and Phoenix exposes no
way to mutate an experiment's metadata afterwards, so the outcome totals live
in `CaseOutcome` and reach the reviewer through the summary logging above. What
the metadata carries is the configuration under which the scores were produced,
which is what makes two runs comparable. It is a parameter of
`client.experiments.run_experiment`
(`resources/experiments/__init__.py:752`) and **not** of `create_dataset`,
which has no such parameter and would raise `TypeError`:

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
        # Kept at 0 deliberately: a retried *task* run spends real Brave and
        # OpenAI credit. Contrast `evaluate_experiment` below.
        retries=0,
    )
```

**Drop the explicit `retries=0` from `evaluate_experiment`** and inherit
Phoenix's default of 3. This is the one place retries are worth having: the
judge is a free-tier OpenRouter endpoint, a 429 costs nothing to retry, and
under this commit's new semantics an un-retried 429 becomes a recorded judge
error that reddens the run indistinguishably from a real quality regression:

```python
    result = await client.experiments.evaluate_experiment(
        experiment=task_result,
        evaluators=evaluators,
        print_summary=True,
        concurrency=1,
        timeout=PHOENIX_TIMEOUT_SECONDS,
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

**Split into 5a and 5b, and the split is load-bearing.** Everything in 5a is
code the implementer can write today. Everything in 5b is case data only the
user can supply, and the plan forbids inventing it. Keeping them as one commit
would make commit 5 unstartable until the user has written four cases, and would
strand the rubric generalisation and the `route_correct` fix behind an editorial
decision they do not depend on. If 5b is delayed indefinitely, 5a still lands
and commit 6 still works over the two existing cases.

**Safe here** because commit 1's run has already recorded the new judge's
scores against the old rubrics, so this commit's effect on scores is
attributable to the rubric change alone.

#### Commit 5a — generalised rubrics, the reporter machinery, the `route_correct` fix

**Files.** `basic_agent_evaluation.py`,
`tests/unit_tests/test_manual_quality_evaluation.py`. **Not `cases.json`.**

This commit adds `run_reporter_thread`, `REPORT_FIDELITY_PROMPT`,
`build_reporter_evaluators`, `"reporter"` in `KNOWN_AGENTS`, the reporter entry
in the dispatch table, the generalised rubrics, and the `route_correct` fix with
its regression test. `cases.json` still holds the two carried-over cases, so the
new reporter path is reachable but unexercised, and `make test` stays green.

##### Generalise the rubrics

Two of the three rubrics have the Finland and Sweden answer key written into
their own scoring rungs, so they cannot score any other question.

- `GROUNDEDNESS_PROMPT` (`basic_agent_evaluation.py:51-55`) is already generic.
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

**One rule binds every rubric in this file: no template may contain a literal
`{` or `}`.** `PromptTemplate` parses the template once at construction and
treats every `{name}` as a variable, so a literal brace in the rubric text
becomes a phantom required field and the evaluator fails at run time with
`ValueError: Missing required field`. Interpolated *values* are safe — they are
substituted after parsing, so a report or a source containing `{"a": 1}` passes
through untouched. Verified empirically against `arize-phoenix-evals` 3.6.0.

**This changes what a score means.** A 4 recorded after this commit is not the
same measurement as a 4 recorded before it. Commit 1's run is the record of the
old scale; treat scores from before this commit and after it as two series.

##### The `route_correct` fix

`route_correct` needs the chained-comparison fix, because the second
orchestrator case may expect a destination other than `geopolitical`:

```python
# Before (`:258`) — passes only when the expected destination is "geopolitical".
    return bool(output.get("destination") == reference["destination"] == "geopolitical")

# After — compares the run against its own case's expectation.
    return bool(output.get("destination") == reference["destination"])
```

**The regression test for this belongs in 5a, not commit 3.** A test asserting
`route_correct` returns `True` for a case expecting `other` fails against the
pre-fix chained comparison, so landing it in commit 3 would leave `make test`
red through commits 3 and 4. It lands here, with the fix it tests.
`create_evaluator`'s wrapper forwards to the raw function, so the test can call
`route_correct(output=..., reference=...)` directly with no Phoenix involvement.

##### 5a's validation

`cd app && make lint && make test`, then a live local run of the two existing
cases. Every judged evaluator must return a score **and** an explanation;
`route_correct` returns a score and a label and **no** explanation, which is
correct and is why its name is excluded from `explanation_names`. Judge errors
must be zero. Compare both cases against commit 1's recorded scores and expect
movement, since the ruler changed.

#### Commit 5b — four new judged cases

**Files.** `cases.json`.

**Gated on the user.** This commit cannot start until the user has supplied the
four cases. The implementer's job here is to bring proposals for review and then
transcribe what comes back, not to author case content.

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

##### The reporter case's data has two hard requirements

The reporter case is the only one needing the resume machinery, and it is the
only eval coverage the reporter agent gets at all. Its `input.messages` must
satisfy two live gates before the interrupt it depends on can ever fire, and
neither is negotiable:

1. **`classify` must live-decide `destination == "report"`** for the crafted
   history (`src/agents/orchestrator/nodes/classify.py:46`). The final user turn
   has to read unmistakably as a request for a written report.
2. **`has_researched_material(state["messages"])` must be true**
   (`src/agents/orchestrator/nodes/reporter.py:50`). Per
   `src/agents/reporter/state.py:95-120` this means at least one *assistant*
   turn in the history must contain a markdown link to `http(s)`. Without one
   the node refuses with `NO_MATERIAL_NOTICE`, never invokes the subgraph, and
   never pauses.

Both belong in the case data the user writes. State them when bringing the case
for review.

##### The task, with its guard

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

async def run_reporter_thread(input: dict[str, Any]) -> dict[str, Any]:
    """Drive a paused reporter turn to completion over an in-memory saver.

    The module-level `agents.orchestrator.graph.graph` is compiled with no
    checkpointer (`graph.py:59`), and `gate` calls `interrupt()`, so a paused
    run cannot be resumed on it. `build_graph` takes the saver for exactly this
    reason (`orchestrator/graph.py:19-28`).

    Not reusable from `run_orchestrator`, which raises on any destination
    outside `{"geopolitical", "other"}` (`basic_agent_evaluation.py:196`).
    """
    from agents.orchestrator.graph import build_graph, build_runtime_config

    graph = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id=f"manual-quality-{uuid4()}")
    messages = [message_from_record(record) for record in input["messages"]]

    result: dict[str, Any] = await graph.ainvoke({"messages": messages}, config=config)
    # Measured against langgraph 1.0.1: resuming a thread with no pending
    # interrupt is a SILENT no-op that returns the completed state and raises
    # nothing. Without this guard, a `classify` misroute or a refusal on
    # `has_researched_material` would let a chat or expert answer flow through
    # every check below — it is still a non-empty `AIMessage` — and be scored by
    # `report_fidelity` as if the reporter had written it. Nothing anywhere
    # would report a problem. Every other task in this file fails loudly on a
    # wrong branch; this is that check.
    if "__interrupt__" not in result:
        raise RuntimeError(
            "Reporter turn never paused: classify did not route to `report`, or "
            "the thread carried no researched material"
        )
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

##### The rubric and its binding

The outline the judge compares against cannot be read back off the parent
graph, because `OrchestratorState` has no outline key. The case therefore
supplies the expected shape in its own `output` as `outline_intent`, a prose
description of what the report should cover. The conversation itself is the
second half of the comparison, and it comes from the case's own `input`:

```python
REPORT_FIDELITY_PROMPT = """
Judge whether the report covers the intended outline and stays within the
research supplied in the conversation. Treat the conversation as the only
evidence available to the report's author.

Conversation:
{conversation}

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
```

The three mapping keys must match the three template variables exactly.
`bind_evaluator` does **not** validate this — verified: it accepts a mapping
with a missing key and one with an extra key without complaint. The mismatch
surfaces only at evaluation time, as a `ValueError: Missing required field` that
Phoenix records as `run.error`, which commit 4 counts as a judge error. That is
why commit 4 requires the first live run of this evaluator to show zero judge
errors.

`reference.*` reads the case's `output` object, matching how
`reference.must_address` and `reference.standalone_query_intent` already work.
`input.messages` is the case's own conversation, the same source
`rewrite_quality` already maps to `history`.

`report_fidelity` is a judged evaluator, so its name goes into
`explanation_names` and into `JUDGED_EVALUATORS`. No CODE evaluator name may
enter `explanation_names`: a CODE result is `{"score": float, "label": str}`
with no explanation key, which is why `route_correct` is already excluded.

##### 5b's validation

`cd app && make lint && make test` — the loader test that reads the real shipped
`cases.json` is what proves the four new entries are schema-valid. Then a full
live local run of all six cases, in which every **judged** evaluator returns a
score and an explanation, `route_correct` returns a score with no explanation,
and judge errors are zero across the run.

### Commit 6 — workflow and guidance

**Files.** `.github/workflows/evals.yml`, `CLAUDE.md`, `AGENTS.md`,
`.github/copilot-instructions.md`.

**Safe here** because the script it invokes is finished and locally proven.

**Blocked until Phoenix Cloud is confirmed reachable.** The workflow has no
degraded mode: `require_env` hard-fails on a missing `PHOENIX_COLLECTOR_ENDPOINT`
and the script raises if `init_tracing()` returns false, so a dispatch without a
working Cloud endpoint and key cannot pass. Confirm the free tier is usable and
the secrets are set **before** starting this commit. If Cloud turns out not to be
viable, commit 6 is simply not landed: commits 1 through 5b stand on their own as
a locally-run suite, and nothing earlier depends on the workflow existing.

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
bare `uv run pytest` (`.github/workflows/unit-tests.yml:32`) collects by
discovery, and a `test_`-prefixed eval file would run live evals on every push.

**All three guidance files change together.** `CLAUDE.md`, `AGENTS.md` and
`.github/copilot-instructions.md` are byte-identical apart from their H1, all
three carry the same "update this file for application-codebase changes" rule
at their top, and every commit in this repository's history that touched one
touched all three. Apply the same edit to each.

The "Operations and validation" section gains: `OPENROUTER_API_KEY` as required
by the eval script, the dispatch-only workflow, and the note that eval scores
are recorded to local Phoenix or Phoenix Cloud depending on the environment.

**The existing sentence needs rewording, not preserving.** It currently reads:

> Manual quality work is `app/tests/manual_quality/basic_agent_evaluation.py`;
> it is advisory and not part of pytest or CI.

Once `.github/workflows/evals.yml` exists and runs that exact script, "not part
of CI" is false. What stays true is that it gates nothing. Replace the clause:

> Manual quality work is `app/tests/manual_quality/basic_agent_evaluation.py`;
> it is advisory, outside pytest, and reachable in CI only through the
> dispatch-only `evals.yml` workflow, which gates no merge.

**Test.** `cd app && make lint && make test`, then one dispatch of the workflow
from the GitHub UI on the feature branch, confirming a green run writes scores
to Phoenix Cloud and a deliberately lowered `JUDGED_SCORE_THRESHOLD` produces a
red one.

## Test plan

**No existing test dies.** The only unit test touching the runner is
`tests/unit_tests/test_manual_quality_evaluation.py`, which parses the runner's
AST and asserts the Phoenix-native output boundary. It must keep passing
unchanged, which constrains the rewrite in two concrete ways: exactly one
`evaluate_experiment` call site, and no `print` of scores, explanations, or
per-experiment headers. The `logger.error` calls added in commit 4 are not
`print`, so they do not trip it. Baseline confirmed: 145 unit tests pass on
`df231a8`.

**New unit tests**, added to `tests/unit_tests/test_manual_quality_evaluation.py`,
all of which run without network access because they exercise the loader and
the pure predicate only.

In **commit 3**:

- `load_cases` rejects a JSON object, an empty list, an entry with a missing or
  extra field, an unknown `agent` value, a blank `id`, and a duplicate `id`.
  Each asserts the specific `ValueError`, using `tmp_path` and monkeypatching
  `CASES_PATH`.
- `load_cases` accepts the real shipped `cases.json`, so the data file and its
  schema check cannot drift apart.

In **commit 5a**, alongside the fix it covers:

- `route_correct` returns `True` when a case's own expected destination
  matches, including a case expecting `other`, which the pre-fix chained
  comparison would have failed. This test **must not** land earlier: it fails
  against the unfixed predicate and would leave `make test` red through commits
  3 and 4.

**Not unit tested**, deliberately: the live tasks, the judge construction, and
the Phoenix client. Mocking them would assert the mock. Their validation is the
live local run named in each commit.

`run_reporter_thread` gets no dedicated unit test either, and this is a
decision rather than an omission. The mechanism it wraps —
`build_graph(checkpointer=InMemorySaver())` driven with
`Command(resume={"action": "approve"})` — is already regression-tested at
`tests/integration_tests/test_orchestrator_graph.py:396`, `:429` and `:458`,
with the reporter child's equivalents at
`tests/integration_tests/test_reporter_graph.py:100-169`. The one behaviour
those tests do not cover is the wrong-branch case, and the `__interrupt__`
guard added in commit 5a *is* the runnable check for it: it fails loudly on
exactly the regression a mocked test would have been written to catch.

**Manual validation gate** before commit 6 is considered done: one full live
local run with every case scored, every judged evaluator carrying an
explanation, and zero judge errors; one run with a bad
`OPENROUTER_API_KEY` producing recorded judge errors and a non-zero exit, and
one workflow dispatch.

## Migration and rollout notes

**Environment.** `OPENROUTER_API_KEY` is new and required by the eval script
only. It goes in the root `.env`, which is never committed and **must not be
modified by the implementation**; the user adds it. `PHOENIX_API_KEY` is
optional and unset locally.

**Repository secrets**, added by the user in GitHub settings:
`OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, `OPENROUTER_API_KEY`,
`PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_API_KEY`.

**No schema or data migration.** Postgres is untouched. `cases.json` is test
data with a single reader.

**Documentation.** All three guidance files — `CLAUDE.md`, `AGENTS.md` and
`.github/copilot-instructions.md` — as described in commit 6. They are
byte-identical apart from their H1 and must stay that way. The brainstorm
artifact is a historical record and is not updated.

**Rollout order.** Commits 1 through 5b are safe to merge before any secret
exists, because the workflow does not exist yet and the script is run by hand.
Commit 6 requires the secrets to be in place first, or its first dispatch fails
on a missing variable.

## Open questions and rejected objections

### Verified against the installed packages

Recorded because several of these were disputed during review. All were settled
by running `app/.venv/bin/python` against the installed versions
(`arize-phoenix-client` 3.3.0, `arize-phoenix-evals` 3.6.0, `arize-phoenix-otel`
0.17.1, `langgraph` 1.0.1). The full `arize-phoenix` package is **not**
installed, and neither is `openinference-instrumentation-openai`.

- `LLM(provider="openai", model=..., api_key=..., base_url=...)` constructs
  cleanly with an OpenRouter model id and sets the async client's base URL. No
  model-name validation, no new dependency.
- `evaluate_experiment` defaults to `retries=3`; `run_experiment` to the same.
  Both also accept `rate_limit_errors`, unused here.
- `experiment_metadata` is a `run_experiment` parameter
  (`resources/experiments/__init__.py:752`, written to the payload at
  `:726-727`), not a `create_dataset` one.
- `LLMEvaluator.__init__` ends `self.invocation_parameters = kwargs`, so any
  extra keyword on `ClassificationEvaluator` reaches the SDK call.
- `PromptTemplate` parses `{name}` at construction. Brace-bearing *values* are
  safe; brace-bearing *templates* are not.
- `bind_evaluator` silently accepts a mismatched `input_mapping`.
- Resuming a thread with no pending interrupt returns the completed state and
  raises nothing.
- Phoenix's evaluator runner wraps execution in `capture_spans(resource)`
  (`.../experiments/__init__.py:137-150`, entered at `:1989`) and
  `phoenix/evals/llm/wrapper.py` decorates its generation methods with `@trace`.
  Judge spans are collected deliberately, so **do not** wrap evaluation in
  `suppress_tracing`.

### Rejected, with the reason

- **"`unit-tests.yml` scopes pytest to `tests/unit_tests`, so the non-`test_`
  filename rule is unnecessary."** Rejected on the file itself:
  `.github/workflows/unit-tests.yml:32` runs a bare `uv run pytest` with no
  path argument. The Makefile's `test` target is scoped, but the workflow is
  not, and the workflow is what runs on every push. The rule stands and its
  stated rationale is correct.
- **"Rewrite the rubrics in mustache syntax with `[BEGIN DATA]` delimiters."**
  Rejected on measurement; see changelog rejection 1.
- **"Wrap evaluation in `suppress_tracing`."** Rejected on two grounds; see
  changelog rejection 2.
- **"Unit-test `run_reporter_thread`'s resume loop."** Rejected as covered; see
  changelog rejection 3.

### Escalated to the user, and resolved

Two reviewers independently attacked a decision the user settled in the
brainstorm, on evidence the user did not have at the time. It was put to the
user rather than reversed unilaterally. The user chose the trimmed shape. See
"Shape decision" at the end.

### Carried from the brainstorm, still unresolved

- **Phoenix Cloud free-tier limits are unverified.** Check before adding the
  `PHOENIX_COLLECTOR_ENDPOINT` and `PHOENIX_API_KEY` secrets. If Cloud is not
  viable, commit 6 is not landed at all — the workflow has no degraded mode —
  and the suite stays local-only. Nothing in commits 1 through 5b depends on it.
- **OpenRouter free-tier rate limits are unmeasured** against a run of this
  size. Phoenix's default `retries=3` on `evaluate_experiment` now absorbs
  transient throttling. The first full run should record whether throttling
  still shows through; if it does, the judged case count is the knob to turn.
- **The four new judged cases are editorial and unchosen.** Two expert topics,
  one ambiguous orchestrator follow-up, and one reporter thread with its
  `outline_intent` and the two hard data requirements named in commit 5b.
  Commit 5b must bring them to the user before writing them into `cases.json`;
  they are not for the implementer to invent.
- **Two of the three judge rubrics name Finland and Sweden facts inside their
  own scoring labels** (`USEFULNESS_PROMPT` labels 4 and 5,
  `REWRITE_QUALITY_PROMPT` labels 1 through 5; `GROUNDEDNESS_PROMPT` is already
  generic and stays unchanged). They must be generalised in commit 5a before
  being applied to any case other than the two they were written for. This is
  the single largest piece of judgement work in the plan and it is editorial, so
  the user should review the rewritten rubrics.
- **The pinned judge has reasoning enabled by default.** OpenRouter's catalogue
  reports `"reasoning": {"mandatory": false, "default_enabled": true}` for
  `nvidia/nemotron-3-super-120b-a12b:free`. Every judge call spends reasoning
  tokens the plan's cost model did not budget, adding latency and free-tier
  throttle pressure. Measure it on the first run. If it matters, disabling it
  needs no custom client: `ClassificationEvaluator` forwards unknown keywords to
  the SDK call through `invocation_parameters`, so
  `extra_body={"reasoning": {"effort": "none"}}` alongside `temperature=0` is
  the whole change.
- **`JUDGED_SCORE_THRESHOLD = 3.0` is a guess** made with no historical scores,
  by the user's explicit decision, and is one constant to change.

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
against the *existing* rubrics before the rubrics are generalised (commit 5a).
That was the reviewers' strongest point and it survives the trim: if
comparability is why the judge is pinned, the judge and the ruler must not move
in the same measurement. Commit 1's recorded run is the bridge between the two
score series.

**Still true after the trim.** The reporter agent's only eval coverage is the
single approve-path case in commit 5b. If that case is also cut, the reporter is
unevaluated. This was flagged to the user when the trim was chosen, and it is
why the `__interrupt__` guard is not optional: a silently misrouted reporter
case would leave the agent unevaluated while appearing to be scored.
