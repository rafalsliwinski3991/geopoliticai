# Plan: simple orchestrator eval with one general LLM judge

**Depth:** lightweight
**Input:** no brainstorm file. This implements the design approved in chat on
2026-09-15 (rs-brainstorming, bounded path). The answers were Q1A, Q2A, Q3B
and Q4A.

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
- **Q3B:** the score is advisory. The script logs judge errors and exits 0.
- **Q4A:** delete the `*_old.py` files and cut the unit test down to one
  dataset-loading test.

Kept from the old script:
- The pinned Nemotron model on OpenRouter.
- Phoenix/AX selection through `get_arize_platform()`.
- `phoenix_base_url()`.
- Getting the dataset before creating it.
- `decode_ax_value`.
- `retries=0` on the orchestrator task.

Non-goals:
- No route check that runs as plain code.
- No per-agent groups for expert, reporter or e2e.
- No OpenRouter call counter.
- No hash-based dataset names.
- No results check after the experiment.
- No change to `evals.yml`, because the script path stays the same.
- No change to CLAUDE.md. Its description of the eval script, which says it is
  advisory and lists the same environment variables, stays true.

Verified against the code:
- `messages_from_dict` parses the `dataset.json` input messages. It returns a
  `HumanMessage` whose `id` is kept.
- `build_runtime_config(thread_id=...)` and `graph` exist in
  `agents/orchestrator/graph.py`.
- `init_environment`, `require_env`, `REQUIRED_ENV_VARS`, `get_arize_platform`
  and `get_trace_endpoint` exist in `config.py`.
- The Phoenix and AX API calls are the same ones the old script already used
  against the installed versions.

## Change steps

1. Delete `app/tests/manual_quality/basic_agent_evaluation_old.py` and
   `app/tests/manual_quality/judge_prompts_old.py`.

2. Create `app/tests/manual_quality/basic_agent_evaluation.py`. Put all
   constants at the top, straight after the imports.

   ```python
   DATASET_PATH = Path(__file__).with_name("dataset.json")
   # Both platforms reuse a dataset found by name and never refresh its
   # examples: bump this whenever dataset.json changes.
   DATASET_NAME = "geopoliticai-orchestrator-v1"
   AGENT_NAME = "orchestrator"
   JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"  # pinned, see git history
   OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
   TIMEOUT_SECONDS = 180
   SCORE_CHOICES: dict[str, float | int] = {str(s): s for s in range(1, 6)}
  ORCHESTRAOR_QUALITY_PROMPT = """
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
   - `async run_orchestrator(input)`: imports the graph inside the function,
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
     `prompt_template=ORCHESTRAOR_QUALITY_PROMPT`, `choices=SCORE_CHOICES`,
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
       - Call `run_experiment(dataset, task=run_orchestrator, evaluators=[bind_evaluator(evaluator=judge, input_mapping={"input": "input", "output": "output", "reference": "reference"})], experiment_name=..., experiment_metadata={"judge_model": JUDGE_MODEL}, concurrency=1, timeout=TIMEOUT_SECONDS, retries=0)`.
       - Log every run in `result["evaluation_runs"]` that has `run.error`.
     - **AX:**
       - Call `client.datasets.get(dataset=DATASET_NAME, space=space_id)`. On
         `NotFoundError`, call `create(...)` with
         `attributes.input.value` / `attributes.output.value` for each example
         and `force_http=True`.
      - Call `client.experiments.run(..., task=sync_task, evaluators={"orchestrator_quality": ax_judge}, concurrency=1, timeout=TIMEOUT_SECONDS)`.
         `sync_task` decodes the input and runs `asyncio.run(run_orchestrator(...))`.
         `ax_judge(*, input, output, dataset_output)` calls
         `judge.evaluate({...decoded...})[0]` and returns an `EvaluationResult`.
         If it raises, it logs the error and returns
         `EvaluationResult(score=0, label="judge_error", explanation=str(exc))`.
       - Wrap every AX call in `asyncio.to_thread`, as before.
     - Return normally. The exit code is always 0.
   - `if __name__ == "__main__": asyncio.run(main())`. The `--validate-cases`
     CLI is dropped.

3. Rewrite `app/tests/unit_tests/test_manual_quality_evaluation.py` as a single
   test. It loads the runner through `importlib.util` the same way the current
   file does, without adding a `judge_prompts` path. It asserts:
   - `load_examples()` is non-empty.
   - For every example, `messages_from_dict(example["input"]["messages"])`
     returns at least one `BaseMessage`.
   - Every `example["output"]` has a `destination` in
     `{"geopolitical", "other", "report"}`.

   The module import must stay free of network and keys. All agent and
   platform imports inside functions stay function-local.

## Validation

From `app/`:
- `uv run pytest tests/unit_tests/test_manual_quality_evaluation.py`
- `make lint`
- `make test`
- Manual, with your keys and a running local Phoenix:
  `uv run python tests/manual_quality/basic_agent_evaluation.py`. Then check
  that the dataset `geopoliticai-orchestrator-v1` and one experiment with a
  `orchestrator_quality` score appear. A second run must reuse the dataset without
  duplicating its examples.

## Required follow-up

None. `evals.yml` still runs the same path with the same environment variables.
