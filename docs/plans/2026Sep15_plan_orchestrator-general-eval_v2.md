# Plan: simple orchestrator eval with one general LLM judge

**Depth:** lightweight
**Input:** no brainstorm file. This implements the design approved in chat on
2026-09-15 (rs-brainstorming, bounded path). The answers were Q1A, Q2A, Q3B
and Q4A.

**Readiness:** Ready for implementation
**User approval:** Approved (2026-09-15)

## Review changes

Source plan: `docs/plans/2026Sep15_plan_orchestrator-general-eval_v1.md`.
Review record: `docs/plan-reviews/2026Sep15_plan_orchestrator-general-eval_review_v1.md`.

| ID | Change | Why |
| --- | --- | --- |
| D1 | Phoenix now makes two calls: `run_experiment(evaluators=None, retries=0)`, then `evaluate_experiment` with its default retries. On AX, `ax_judge` retries `JUDGE_RETRIES = 3` times before returning `judge_error`. | In `arize-phoenix-client` 3.3.0, `run_experiment` passes its `retries` on to the evaluators. The v1 single call would have left the free judge with no retries, while a failed task must still not re-spend credit. |
| D2 | `evals.yml` and CLAUDE.md stay unchanged (out of scope). The claim that CLAUDE.md is fully accurate is removed, and the trigger mismatch moves to follow-up. | `evals.yml` currently runs on `pull_request`, but CLAUDE.md says "dispatch-only". This mismatch predates the plan. Accepted risk: live evals keep spending credit on every PR push. |
| D3 | If any orchestrator task run fails, the script logs it and exits 1 after judging. Judge errors stay log-only. | Both platforms catch task exceptions, so v1 would exit 0 even with a broken app. Q3B only made the score advisory. Accepted risk: a flaky OpenAI or Brave call turns the PR check red. |
| D4 | Q4A's single unit test is kept. Validation gains a manual run with a bogus `OPENAI_API_KEY` that must exit 1. | Keeps the test code small. Accepted risk: nothing catches a regression in the D1 or D3 branches automatically. |

Corrections made without a decision:
- Fixed the `ORCHESTRAOR_QUALITY_PROMPT` typo and the code-block indentation.
- The manual crash check uses a bogus `OPENAI_API_KEY`, not `BRAVE_SEARCH_KEY`. The only dataset example ("Hello") routes to `chat`, which never calls Brave.

Noted, not changed: the judge sees full serialized messages, including random ids and `response_metadata`. Q2A settled what the judge sees, and the prompt names the fields to compare.

## Scope and non-goals

Replace the 788-line multi-group runner with a small script. It runs the
orchestrator graph on every example in `dataset.json` and scores each run with
one general LLM judge on Phoenix or Arize AX.

Settled decisions:
- **Q1A:** `DATASET_NAME` is a module constant. The script gets the dataset by
  name and uploads `dataset.json` only if it is missing. You bump the name
  whenever the JSON changes.
- **Q2A:** the judge sees the input, the actual output and the expected output.
  It scores 1–5 with an explanation.
- **Q3B:** the score is advisory. Judge errors are logged and never change the
  exit code.
- **D3:** a failed orchestrator task run makes the script exit 1.
- **Q4A:** delete the `*_old.py` files and cut the unit test down to one
  dataset-loading test.

Kept from the old script:
- The pinned Nemotron model on OpenRouter.
- Phoenix/AX selection through `get_arize_platform()`.
- `phoenix_base_url()`.
- Getting the dataset before creating it.
- `decode_ax_value`.
- `retries=0` on the orchestrator task.
- Phoenix judge retries through a separate `evaluate_experiment` call, plus the AX judge retry loop (D1).

Non-goals:
- No route check that runs as plain code.
- No per-agent groups for expert, reporter or e2e.
- No OpenRouter call counter.
- No hash-based dataset names.
- No score threshold and no structural validation of evaluation results.
- No change to `evals.yml` (D2).
- No change to CLAUDE.md. Its description of the eval script (advisory, same
  environment variables) still holds. Its "dispatch-only" wording for `evals.yml` is
  already inaccurate; see follow-up.

Verified against the code:
- `messages_from_dict` parses the `dataset.json` input messages. It returns a
  `HumanMessage` whose `id` is kept.
- `build_runtime_config(thread_id=...)` and `graph` exist in
  `agents/orchestrator/graph.py`.
- `init_environment`, `require_env`, `REQUIRED_ENV_VARS`, `get_arize_platform`
  and `get_trace_endpoint` exist in `config.py`.
- The Phoenix and AX API calls are the ones the old script already used
  against the installed versions (`arize-phoenix-client` 3.3.0,
  `arize-phoenix-evals` 3.6.0, `arize` 8.52.1).
- Both platforms catch task exceptions instead of raising. Phoenix stores them as
  `task_run["error"]`. AX puts them in the `error` column of the result
  dataframe.

## Change steps

1. Delete `app/tests/manual_quality/basic_agent_evaluation_old.py` and
   `app/tests/manual_quality/judge_prompts_old.py`.

2. Create `app/tests/manual_quality/basic_agent_evaluation.py`. Put all
   constants at the top, straight after the imports. It must pass
   `mypy --strict` through `make lint`.

   ```python
   DATASET_PATH = Path(__file__).with_name("dataset.json")
   # Both platforms reuse a dataset found by name and never refresh its
   # examples: bump this whenever dataset.json changes.
   DATASET_NAME = "geopoliticai-orchestrator-v1"
   AGENT_NAME = "orchestrator"
   JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"  # pinned, see git history
   OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
   TIMEOUT_SECONDS = 180
   JUDGE_RETRIES = 3
   SCORE_CHOICES: dict[str, float | int] = {str(s): s for s in range(1, 6)}
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
   ```

   Functions:
   - `load_examples() -> list[dict]`: return the `data` of the entry whose
     `agent_name == AGENT_NAME`. Keep only `input` and `output`. Raise
     `ValueError` if the entry is missing or empty.
   - `phoenix_base_url()`: copy it unchanged from the old script.
   - `decode_ax_value()`: copy it unchanged from the old script.
   - `async run_orchestrator(input)`: import the graph inside the function,
     for the same reason as before (module-scope `init_tracing`).
     ```python
     result = await graph.ainvoke(
         {"messages": messages_from_dict(input["messages"])},
         config=build_runtime_config(thread_id=f"manual-quality-{uuid4()}"),
     )
     return {
         "messages": messages_to_dict(result["messages"]),
         "destination": result.get("destination"),
         "standalone_query": result.get("standalone_query"),
     }
     ```
   - `build_judge(llm) -> ClassificationEvaluator`: `name="orchestrator_quality"`,
     `prompt_template=ORCHESTRATOR_QUALITY_PROMPT`, `choices=SCORE_CHOICES`,
     `include_explanation=True` and `temperature=0`.
   - `async main()`:
     - `examples = load_examples()`, then `init_environment()` and
       `require_env((*REQUIRED_ENV_VARS, "OPENROUTER_API_KEY"))`.
     - Choose the platform and call `init_tracing()` as the old `main` did.
     - Build `LLM(provider="openai", model=JUDGE_MODEL, api_key=..., base_url=OPENROUTER_BASE_URL)`.
     - Set `experiment_name = f"{AGENT_NAME}-{utc timestamp}"`.
     - **Phoenix:**
       - Call `get_dataset(dataset=DATASET_NAME)`. On `ValueError`, call
         `create_dataset(name=DATASET_NAME, examples=examples)` instead.
       - `task_result = await run_experiment(dataset=dataset, task=run_orchestrator, evaluators=None, experiment_name=..., experiment_metadata={"judge_model": JUDGE_MODEL}, print_summary=False, concurrency=1, timeout=TIMEOUT_SECONDS, retries=0)`.
         Keep a comment explaining that `run_experiment` forwards `retries` to its
         evaluators, which is why the judge runs in a second call (D1).
       - `eval_result = await evaluate_experiment(experiment=task_result, evaluators=[bind_evaluator(evaluator=judge, input_mapping={"input": "input", "output": "output", "reference": "reference"})], print_summary=True, concurrency=1, timeout=TIMEOUT_SECONDS)`.
         Leave `retries` at the default of 3.
       - Log every run in `eval_result["evaluation_runs"]` that has `run.error`.
       - `failed_tasks = [run["error"] for run in task_result["task_runs"] if run.get("error")]`.
     - **AX:**
       - Call `client.datasets.get(dataset=DATASET_NAME, space=space_id)`. On
         `NotFoundError`, call `create(...)` with
         `attributes.input.value` / `attributes.output.value` for each example
         and `force_http=True`.
       - Call `client.experiments.run(..., task=sync_task, evaluators={"orchestrator_quality": ax_judge}, concurrency=1, timeout=TIMEOUT_SECONDS)`.
         `sync_task` decodes the input and runs `asyncio.run(run_orchestrator(...))`.
         `ax_judge(*, input, output, dataset_output)` calls
         `judge.evaluate({...decoded...})[0]` up to `JUDGE_RETRIES` times and
         returns the first successful `EvaluationResult`. If every attempt raises,
         it logs the last error and returns
         `EvaluationResult(score=0, label="judge_error", explanation=str(exc))`.
       - `failed_tasks = [row["error"] for row in ax_result.to_dict(orient="records") if row.get("error")]`.
       - Wrap every AX call in `asyncio.to_thread`, as before.
     - After either platform: log each entry in `failed_tasks`. If the list is
       non-empty, `raise SystemExit(1)` (D3). Otherwise return normally (exit 0),
       including when the judge had errors.
   - `if __name__ == "__main__": asyncio.run(main())`. The `--validate-cases`
     CLI is dropped.

3. Rewrite `app/tests/unit_tests/test_manual_quality_evaluation.py` as a single
   test. (The working-tree version is currently broken because it references the
   deleted `cases.json` and `judge_prompts.py`.) Load the runner through
   `importlib.util` the same way the current file does, without adding a
   `judge_prompts` path. Assert that:
   - `load_examples()` is non-empty.
   - For every example, `messages_from_dict(example["input"]["messages"])`
     returns at least one `BaseMessage`.
   - Every `example["output"]` has a `destination` in
     `{"geopolitical", "other", "report"}`.

   Importing the module must not touch the network or need keys. All agent and
   platform imports inside functions stay function-local.

## Validation

From `app/`:
- `uv run pytest tests/unit_tests/test_manual_quality_evaluation.py`
- `make lint`
- `make test`
- Manual, with your keys and a running local Phoenix:
  - `uv run python tests/manual_quality/basic_agent_evaluation.py` exits 0.
    Check that the dataset `geopoliticai-orchestrator-v1` and one experiment with
    an `orchestrator_quality` score appear. A second run must reuse the dataset
    without duplicating its examples.
  - `OPENAI_API_KEY=invalid uv run python tests/manual_quality/basic_agent_evaluation.py`
    logs the failed task run and exits 1 (D3). Check with `echo $?`.
    The shell value wins, because `init_environment` calls `load_dotenv` with its
    default `override=False`.

## Required follow-up

- `.github/workflows/evals.yml` triggers on `pull_request` with
  `workflow_dispatch` commented out (commit `52d54de`, "tmp change"). CLAUDE.md
  calls it dispatch-only. Resolve this separately, either by restoring the dispatch
  trigger or by updating CLAUDE.md (D2).
