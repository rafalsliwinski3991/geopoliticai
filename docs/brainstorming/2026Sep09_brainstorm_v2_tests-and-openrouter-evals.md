# Unit test reorganisation and an OpenRouter-judged edge-case eval suite

**Started:** 2026-09-09
**Status:** Complete
**Mode:** batch (similar questions per round, default)

Two subprojects, run in order:

1. **Unit tests** (bounded) — move node tests into a `nodes/` subdirectory and
   add Arrange/Act/Assert comment markers across the whole suite.
2. **Evals** (architectural) — expand from two happy-path smoke cases to an
   edge-case suite, judged by a pinned free OpenRouter model, runnable by hand
   against local Phoenix or from a manually dispatched GitHub Actions workflow
   against Phoenix Cloud.

## Target design

### Shapes considered

Three overall shapes were on the table. The chosen one is listed first.

1. **Extend the standalone script, one client, two Phoenix destinations.**
   Chosen. Keeps `basic_agent_evaluation.py` as a plain script the user runs by
   hand or a workflow dispatches. One `phoenix.client.AsyncClient` built from
   environment variables points at either the local Compose Phoenix or Phoenix
   Cloud. Deterministic edge cases are CODE evaluators; judged cases use
   `ClassificationEvaluator` against OpenRouter.
2. **Evals as pytest tests on Phoenix's pytest plugin.** Rejected. The plugin
   is already installed and is Phoenix's supported CI path, and it would delete
   runner plumbing and turn deterministic cases into plain asserts. Rejected
   because it welds live, money-spending evals into the same runner as the free
   unit tests, and contradicts `CLAUDE.md`'s rule that eval work sits outside
   pytest and CI.
3. **Standalone script writing to Arize AX from CI.** Rejected. AX needs the
   separate `arize` SDK, a differently shaped gRPC experiment API, and
   evaluators expressed twice, making it the most expensive option. The user's
   requirement was hosted visibility of CI results, which Phoenix Cloud
   satisfies with the client the script already builds.

### Unit tests

The test tree mirrors `src/agents/<name>/` exactly. Nine node test files move
into `nodes/` subdirectories with new `__init__.py` files, including a
two-file `expert/nodes/`. `test_state.py` and `test_intent.py` stay at the
agent level, mirroring `state.py` and `intent.py`. All 23 unit test files gain
`# Arrange`, `# Act` and `# Assert` comment markers. The file moves and the
comment sweep are separate commits so the structural change stays reviewable.

### Evals

`app/tests/manual_quality/basic_agent_evaluation.py` remains the entrypoint and
keeps a non-`test_` filename so the existing `uv run pytest` workflow never
collects it. It grows from 2 cases to 8-12 covering both deterministic and
judgement-dependent paths, run fully live against real Brave and real OpenAI.

- **Cases** live in one `cases.json` holding a list. Each entry names the agent
  it runs against, since the runner can no longer infer that from a dict key.
- **Deterministic cases** — refusal, cancel, revision cap, `other` routing,
  truncation — are scored by `@create_evaluator(kind="CODE")` predicates with
  no model call, following the existing `route_correct`.
- **Judged cases** keep `ClassificationEvaluator` on the 1-5 scale with
  explanations.
- **The judge** is `nvidia/nemotron-3-super-120b-a12b:free`, pinned, reached as
  `LLM(provider="openai", model=..., api_key=..., base_url=...)` with
  OpenRouter's base URL. No new dependency. `OPENROUTER_API_KEY` is required.
- **Judge failures** — throttling, or a strict-schema rejection — are recorded
  per case through `log_evaluation`'s `error` argument and the run continues.
  The experiment metadata records the case count and the failure count so a
  partially scored run is never silently compared against a complete one.
- **Destination** is one `AsyncClient` built from a Phoenix base URL and an
  optional API key. Local runs reach the Compose Phoenix; workflow runs reach
  Phoenix Cloud.
- **The workflow** is `workflow_dispatch` only. It never runs on push or pull
  request and never gates a merge. Brave, OpenAI, OpenRouter and Phoenix Cloud
  credentials are repository secrets.
- **The workflow goes red** when a judged score falls below 3, when a CODE
  evaluator fails, or when any score is missing because the run was invalid.

The exact case list and its expected values are deliberately left to the
implementation plan, since they are derivable from the graph rather than being
decisions.

## Context verified

Repository-local:

- Nine node test files sit flat in `app/tests/unit_tests/agents/<agent>/`:
  expert `test_answer.py`, `test_search_and_fetch.py`; orchestrator
  `test_chat.py`, `test_classify.py`, `test_expert.py`, `test_reporter.py`;
  reporter `test_gate.py`, `test_outline.py`, `test_write.py`.
- Three test files in those same directories are *not* node tests:
  orchestrator `test_state.py`, reporter `test_state.py`, reporter
  `test_intent.py`. They correspond to `state.py` and `intent.py` in `src/`.
- `app/tests/unit_tests/agents/expert/consts/test_sources.py` is the only place
  the test tree already mirrors a `src/` subdirectory.
- 23 unit test files total. No AAA comment markers anywhere in the suite.
- `app/tests/manual_quality/basic_agent_evaluation.py` runs exactly two live
  end-to-end cases (expert Finland/NATO, orchestrator Sweden follow-up) from
  `cases.json`, with a judge pinned to `gpt-4o-mini-2024-07-18`. It is advisory,
  outside pytest and CI, per `CLAUDE.md`.
- Existing evaluators: `groundedness`, `usefulness`, `rewrite_quality` are
  Phoenix `ClassificationEvaluator`s on a 1-5 scale; `route_correct` is a
  `@create_evaluator(kind="CODE")` Python predicate needing no model call.
- The `ai_council` branch prototype `prototypes/ai_council.py` calls OpenRouter
  directly over `httpx`, posts `response_format: {"type": "json_schema",
  "strict": true}`, and defaults members to `openrouter/free`.

External, verified against installed packages and live APIs:

- `phoenix.evals.LLM.__init__` forwards arbitrary `**kwargs` (and
  `async_client_kwargs`) to the underlying SDK client constructor, explicitly
  documenting `api_key` and `base_url`. OpenRouter is therefore reachable as
  `provider="openai"` with OpenRouter's base URL and key, adding no dependency.
- Phoenix's OpenAI adapter (`phoenix/evals/llm/adapters/openai/adapter.py`,
  lines 255-266 and 316-327) hardcodes `response_format` of type `json_schema`
  with `"strict": True` for every object generation. A judge model that does
  not support strict schemas fails hard rather than scoring badly.
- OpenRouter's live catalogue holds 431 models, of which 18 end in `:free`, and
  only 5 of those declare `structured_outputs`:
  `nvidia/nemotron-3-super-120b-a12b:free`,
  `dots-studio/dots-3-note-preview:free`, `nex-agi/nex-n2.5-mini:free`,
  `nex-agi/nex-n2.5-pro:free`, `liquid/lfm-2.5-2.6b:free`.
- `openrouter/free` is a real router model id that declares both
  `response_format` and `structured_outputs`. `openrouter/auto` does too, but
  is not free.
- `.github/workflows/unit-tests.yml` is the only existing workflow. It runs on
  every push and pull request and executes a bare `uv run pytest` from `app/`.
  There is no `[tool.pytest]` section in `app/pyproject.toml`, so that command
  collects `tests/integration_tests` as well as `tests/unit_tests`.
  `tests/manual_quality/basic_agent_evaluation.py` escapes collection only
  because its filename does not start with `test_`.
- Phoenix is a Compose service (`arizephoenix/phoenix:version-20.4.0`) backed
  by the `phoenix_data` Docker volume, reachable at
  `http://phoenix:6006/v1/traces` from inside Compose only. No Phoenix instance
  exists that a GitHub Actions runner could reach.
- `basic_agent_evaluation.py` hard-requires Phoenix: it raises if
  `init_tracing()` returns false, and every case goes through
  `client.datasets.create_dataset` and `client.experiments.run_experiment`.
- `arize-phoenix-client` 3.3.0 (already installed and locked) registers
  `phoenix.client.pytest.plugin` as a `pytest11` entry point. The
  `@pytest.mark.phoenix` marker and the `log_output`, `log_evaluation` and
  `evaluate` helpers are importable in this venv today with no dependency
  change. The `pytest` extra only adds a `pytest>=7` requirement.
- Phoenix's documented CI pattern (verified via Context7 against
  arize.com/docs) passes `PHOENIX_ENDPOINT` and `PHOENIX_API_KEY` as repository
  secrets and points at a reachable Phoenix. No export-then-import artifact
  flow is documented; the `log_run`/`log_evaluation` replay path is real public
  API but unpaved.
- In the pytest plugin's model a failing evaluator does not fail the test.
  `assert` statements gate CI; evaluator scores are recorded and trended.
- Phoenix Cloud is the hosted Phoenix, reached with the same
  `phoenix.client.Client(base_url=..., api_key=...)` already used here
  (`base_url` of the form `https://app.phoenix.arize.com/s/<space>`). Adopting
  it changes two arguments, not the runner.
- Arize AX is a separate enterprise product with its own `arize` SDK and a
  different experiment API (`client.experiments.run(...)`, gRPC by default). It
  is not reachable with `phoenix.client` and would mean a new dependency and a
  rewritten runner.
- Phoenix's OpenAI adapter sends `model=self.model_name` on every call and
  never reads the resolved model back off the response
  (`llm/adapters/openai/adapter.py`, lines 100, 120, 264, 285, 325, 346). With
  a router model id, the recorded judge identity is the router name, not the
  model that actually scored the case. `Score` does carry a free-form
  `metadata` dict (`evaluators.py` line 193), so the resolved model can be
  recorded explicitly.

## Settled decisions

- **AAA markers sweep the whole suite** — every one of the 23 unit test files
  gets `# Arrange` / `# Act` / `# Assert` comments now, not just the files this
  project touches. _(rationale: a convention half the suite ignores is worth
  nothing; comment-only edits cannot change behaviour)_
  - Challenged on: nothing. No objection raised — a comment sweep is invisible
    to `ruff` and `mypy` and cannot regress the suite.
  - Consequences: one large mechanical diff across `tests/unit_tests/`. The
    nine structural file moves land inside a much bigger comment diff, so they
    should be a separate commit to stay reviewable.

- **Evals cover deterministic and judgement paths end to end** — refusal,
  cancel, revision cap, routing to `other`, and truncation all get eval cases
  alongside groundedness, usefulness, rewrite quality, and report fidelity.
  _(rationale: unit tests mock the interrupt and the model, so they prove node
  logic but never prove a real run actually produces a refusal)_
  - Challenged on: cost and rate limits — live cases for behaviour already
    covered deterministically, drawn against a free judge's daily allowance →
    held, on the grounds that integration-level wiring regressions are exactly
    what the unit tests cannot catch.
  - Consequences: the case count grows from 2 to roughly 8-12. Rate-limit
    pressure becomes a first-class design constraint, which is what makes the
    scoring-mechanism question (Q5) high leverage.

- **OpenRouter free tier is the only judge** — the paid `gpt-4o-mini` judge is
  removed rather than kept as a panel member or fallback. _(rationale: the evals
  are advisory, so a failed run costs a re-run, not a broken release)_
  - Challenged on: a silently swapped or deprecated free model makes scores
    incomparable across runs, defeating the point of recording them in Phoenix
    → held after the catalogue check narrowed the viable pool to 5 models plus
    the `openrouter/free` router.
  - Consequences: `JUDGE_MODEL` and the `LLM(provider="openai", ...)`
    construction change. A new required environment variable appears. Judge
    model choice (Q4) becomes the decision that governs score comparability.

- **Deterministic cases use CODE evaluators** — refusal, cancel, revision cap,
  `other` routing and truncation are checked by plain Python predicates with no
  model call, exactly like the existing `route_correct`. _(rationale: nothing
  for a judge to weigh, and it keeps the whole free-tier allowance for cases
  that need judgement)_
  - Challenged on: nothing substantive. Two scoring mechanisms is two code
    paths, but the pattern already exists in the file.
  - Consequences: judge calls scale with the judgement cases only, roughly
    halving free-tier pressure.

- **Every eval case runs fully live** — real Brave search and real OpenAI on
  every run, no recorded or replayed fixtures. _(rationale: the point of
  covering deterministic paths end to end was to catch integration wiring, and
  replay throws exactly that away)_
  - Challenged on: a suite that costs money per run and fails on flaky search
    is a suite that gets abandoned, which is what happened to the two-case
    version → held.
  - Consequences: roughly 30 Brave calls and 10 OpenAI calls per full run.
    Search flakiness will surface as case failures; the runner must
    distinguish an invalid run from a low score.

- **Cases live in one `cases.json` holding a list** — the two-key dict and the
  `set(raw) != CASE_NAMES` check are replaced by a list with a per-entry schema
  check. _(rationale: one file, one loader, one place to look, and easier to
  diff than three per-agent files)_
  - Challenged on: nothing substantive. It grows long, but a few hundred lines
    of case data in one file is not a real cost.
  - Consequences: `CASE_NAMES` and `CASE_FIELDS` validation is rewritten. Each
    entry needs to name which agent it runs against, since the runner can no
    longer infer that from the key.

- **The test tree mirrors `src/agents/<name>/` exactly** — nine node tests move
  into `nodes/` subdirectories, including a two-file `expert/nodes/`.
  `test_state.py` and `test_intent.py` stay at the agent level because
  `state.py` and `intent.py` sit at the agent level in `src/`. _(rationale: one
  rule with no exceptions beats a judgement call per file)_
  - Challenged on: a directory holding two files is ceremony → held.
  - Consequences: new `__init__.py` files under each `nodes/` directory, and
    the imports in the moved files are unaffected since they use
    `importlib.import_module` on absolute module paths.

- **Evals run as a manually dispatched GitHub Actions workflow** — not a merge
  gate, not local-only. A `workflow_dispatch` job the user triggers from the
  GitHub UI. _(rationale: keeps the suite advisory as `CLAUDE.md` records, while
  removing the reason the two-case version stopped being run)_
  - Challenged on: the runner hard-requires a Phoenix instance that no GitHub
    runner can reach, since Phoenix is a Compose-only service on a Docker
    volume → held, and the objection became Q10 rather than a revision.
  - Consequences: Brave, OpenAI and OpenRouter keys become repository secrets.
    Result storage (Q10) and red-build criteria (Q11) are now live questions.
    The eval entrypoint must keep a non-`test_` filename or the existing
    `uv run pytest` workflow will collect it.

- **The eval runner stays a standalone script, not pytest** — Phoenix's
  already-installed pytest plugin is deliberately not adopted. _(rationale: the
  user wants one script they can trigger by hand locally or from a workflow;
  `CLAUDE.md`'s rule that eval work is outside pytest and CI stays true)_
  - Challenged on: the plugin deletes runner plumbing and is Phoenix's
    supported path → held. Its cost is welding live money-spending evals into
    the same runner as the free unit tests.
  - Consequences: Q5 (CODE evaluators) and Q8 (one `cases.json` list) stand
    unchanged. The runner keeps its own dataset and experiment plumbing. The
    entrypoint keeps a non-`test_` filename.

- **One script, two destinations, both Phoenix** — the script writes to the
  local Compose Phoenix when run by hand and to Phoenix Cloud when run from the
  workflow. Arize AX is dropped. _(rationale: the user's actual requirement was
  "see results from GitHub", not AX specifically; Phoenix Cloud satisfies it
  with the same client the script already builds)_
  - Challenged on: AX needs the separate `arize` SDK, a differently shaped
    experiment API over gRPC, and evaluators written twice, making it the most
    expensive item on the table → user confirmed AX was a means, not an end.
  - Consequences: the script reads a Phoenix base URL and an optional API key
    from the environment and constructs one `AsyncClient` either way. No
    destination abstraction, no second SDK, no lockfile change. `PHOENIX_API_KEY`
    and the Cloud base URL become repository secrets alongside the Brave,
    OpenAI and OpenRouter keys. Q10 is settled by this as option C1.

- **The judge is one pinned free model** — `nvidia/nemotron-3-super-120b-a12b:free`,
  not the `openrouter/free` router. _(rationale: editing one constant on the day
  a model is retired is cheaper than a year of scores that cannot be
  interpreted)_
  - Challenged on: this reverses the round-2 answer. The reversal was driven by
    a verified fact — Phoenix sends the configured model name and never reads
    back the resolved one, and `ClassificationEvaluator` never exposes the raw
    response, so with a router nothing records which model actually scored.
  - Consequences: `JUDGE_MODEL` becomes an OpenRouter model id. Scores stay
    comparable across runs. Model retirement becomes a known maintenance event
    with a documented one-constant swap.

- **Judge failures are recorded per case and the run continues** — a 429 or a
  strict-schema rejection is stored through `log_evaluation`'s `error`
  argument rather than aborting. _(rationale: ten live cases cost real Brave and
  OpenAI calls, and discarding all of them because the free judge blinked is
  expensive)_
  - Challenged on: it contradicts the repo's deliberate no-degraded-fallbacks
    stance, and a partially scored experiment sits in Phoenix next to complete
    ones → held.
  - Consequences: the experiment metadata must record the case count and the
    failure count, so a six-scored run is never silently compared against a
    ten-scored one. This is the one place the design accepts a partial result.

- **The workflow goes red on quality, not only on validity** — a judged score
  below 3, a failing CODE evaluator, or a missing score all fail the job.
  _(rationale: a job green regardless of answer quality gives nothing at a
  glance)_
  - Challenged on: no historical scores exist, so any threshold is a guess, and
    a wrong one trains the user to ignore red → held, with the mitigation that
    the bar starts permissive at 3 and is one constant to change. Red is also
    safe here because nothing merges on this workflow.
  - Consequences: a threshold constant enters the runner. It is explicitly
    provisional and should be revisited once real runs exist.

- **The exact case list is deferred to the implementation plan** — the 8-12
  cases and their expected values are derived from the graph's paths during
  planning, not fixed here. _(rationale: the list is work derivable from the
  code, not a decision)_
  - Challenged on: expected values for judged cases are editorial and get less
    attention inside a plan → held.
  - Consequences: the plan must surface the case list for review rather than
    burying it, and must generalise the three judge rubrics, which currently
    name Finland and Sweden facts inside their own scoring labels.


## Design tree

- Unit tests
  - AAA marker scope — **SETTLED** (whole suite, all 23 files)
  - Directory layout — **SETTLED** (mirror `src/agents/<name>/` exactly)
- Evals
  - Overall shape — **SETTLED** (standalone script, not the pytest plugin)
  - Edge case scope — **SETTLED** (deterministic + judgement)
    - Deterministic scoring — **SETTLED** (CODE evaluators, no model call)
    - Live dependencies — **SETTLED** (fully live every run)
    - Case data shape — **SETTLED** (one `cases.json` list)
    - Exact case list — **PRUNED** to the implementation plan (Q16)
  - Judge
    - Provider — **SETTLED** (OpenRouter free tier only)
    - Model identity — **SETTLED** (pinned `nemotron-3-super-120b-a12b:free`)
    - Failure handling — **SETTLED** (per-case error, run continues)
  - Operation
    - Advisory vs gate — **SETTLED** (manual `workflow_dispatch`, never a gate)
    - Result destination — **SETTLED** (local Phoenix / Phoenix Cloud, one client)
    - Arize AX — **PRUNED** (means, not end; Phoenix Cloud satisfies it)
    - Red-build criteria — **SETTLED** (below 3, CODE failure, or missing score)

## Current frontier (open questions)

None. Every branch was visited or explicitly pruned.

## Carried as flags, not decisions

- Phoenix Cloud's current free-tier limits are unverified. Check before wiring
  the workflow secret.
- OpenRouter free-tier rate limits, per minute and per day, are unmeasured
  against a 10-case run. The first full run should record throttling behaviour.
- `nvidia/nemotron-3-super-120b-a12b:free` will eventually be retired. The
  swap procedure is: pick another model from the free list that declares
  `structured_outputs`, and change one constant. Only five qualify today.
- The judged rubrics in `GROUNDEDNESS_PROMPT`, `USEFULNESS_PROMPT` and
  `REWRITE_QUALITY_PROMPT` were written for two specific Finland and Sweden
  cases and name those facts in their own scoring labels. They must be
  generalised before being applied to 8-12 cases.
- The threshold of 3 is a guess made with no historical scores. Revisit after
  the first few runs. It is one constant.
- `CLAUDE.md` needs updating: the manual quality section must record the
  workflow, the OpenRouter judge and the new required environment variable.
- `app/pyproject.toml` has no `[tool.pytest]` section, so `uv run pytest`
  collects integration tests in CI today. Unchanged by this work, but worth
  knowing before touching the workflow.
- The eval entrypoint must keep a filename that does not start with `test_`.

## Round log

### Round 7 — Q15: threshold numbers, Q16: case list now or in the plan
Leans were fail below 3 with missing scores red, and defer the list.
**User answered:** Q15 A, Q16 B. Neither drew an objection.

### Round 6 — Q4R: judge identity, Q14: judge failure handling, Q11: red criteria
Leans were pin a model, hard error, and invalid runs only.
**User answered:** Q4R B (pin), Q14 B (per-case error, continue), Q11 red on a
score threshold.
**Pushed back on** Q11 — no historical scores exist, so any threshold is a
guess and a wrong one trains the user to ignore red → held, and the objection
became Q15, which fixed the number at 3 and made it explicitly revisable. Q4R
drew no objection. Q14 was accepted with the consequence that partial runs must
record their case and failure counts.

### Round 6 — Q4R: judge identity, Q14: judge failure handling, Q11: red criteria
Posed after Q12 and Q13 closed the shape questions. Pending.

### Round 5b — Q13: how one script reaches two destinations
Asked whether the CI destination is Phoenix Cloud or Arize AX, having verified
AX needs a separate SDK and a rewritten runner.
**User answered:** Q12 A (standalone script), and on AX "I just want to see
results from github".
**Pushed back on** the dual-backend cost before asking → the user's requirement
turned out to be hosted visibility, not AX, so Q13 resolved to Phoenix Cloud
and Q10 to C1.

### Round 5 — Q12: standalone script or pytest plugin
User asked for a Context7 check of the GitHub Actions and Phoenix plan, then
asked about Arize AX. The check found Phoenix's already-installed pytest
plugin, its documented CI pattern requiring a reachable endpoint, and its
assert-gates/scores-trend model. Arize AX was established as a separate SDK
that would mean rewriting the runner, so Q10's hosted option split into
Phoenix Cloud (C1) and Arize AX (C2). Q12 posed ahead of Q10. Pending.

### Round 4 — Q10: eval result storage, Q11: red-build criteria
Posed after verifying Phoenix is unreachable from a GitHub runner. User did
not answer directly; asked whether results could be downloaded from GitHub and
imported into a local Phoenix. Verified yes, via `experiments.create`,
`log_run` and `log_evaluation`, with spans additionally available through
`spans.get_spans`/`spans.log_spans`. Q10 re-posed with that as Option A/B.
Pending.

### Round 3 — Q7: test layout, Q8: case data shape, Q9: advisory or gate
Leans were mirror exactly, per-agent files, stays advisory.
**User answered:** Q7 mirror exactly, Q8 B (single list file), Q9 neither — a
manually dispatched GitHub Actions workflow.
**Pushed back on** Q9 with the verified fact that the runner requires a
Phoenix instance no GitHub runner can reach → held; the objection became Q10.
Q7 and Q8 drew no objection.

### Round 2 — Q4: judge model identity, Q5: deterministic scoring, Q6: live dependencies
Leans were A (pin one model), A (CODE evaluators), A (fully live).
**User answered:** Q4 B, Q5 A, Q6 A.
**Pushed back on** Q4 with a verified fact — Phoenix records the configured
model name, never the resolved one, so the router erases judge identity from
the stored scores → re-check open. Q5 drew no objection. Q6 held against the
cost-and-flakiness objection.

### Round 1 — Q1: AAA comment scope, Q2: eval edge case scope, Q3: judge provider
Asked whether AAA markers sweep all 23 files or only touched ones; whether
evals cover deterministic paths as well as judgement-dependent ones; and
whether OpenRouter replaces the paid judge, joins it as a panel, or backs it up.
Leans were A (sweep all), A (judgement only), A (OpenRouter alone).
**User answered:** Q1 A, Q2 B, Q3 A.
**Pushed back on** Q2+Q3 together — more live cases drawn against a
rate-limited free judge — and verified the OpenRouter catalogue, which showed
only 5 free models support the strict JSON schema Phoenix requires → both held.
Q1 drew no objection.