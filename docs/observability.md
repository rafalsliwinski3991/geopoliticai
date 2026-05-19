# Observability

GeopoliticAI is wired for LangSmith tracing out of the box. Set
`LANGCHAIN_TRACING_V2=true`, `LANGSMITH_API_KEY`, and
`LANGSMITH_PROJECT` in the runtime environment (see `.env.example`).
Every LLM call, tool invocation, and node transition is captured with
no code changes.

## What to monitor

| Signal                          | Why                                                    | Source                          |
| ------------------------------- | ------------------------------------------------------ | ------------------------------- |
| **Per-node p50/p95 latency**    | Find the slowest node before users notice              | LangSmith run timing            |
| **Per-tool failure rate**       | Brave Search / OpenAI quota or outage detector         | LangSmith run errors            |
| **Token usage per graph run**   | Cost tracking — Opus vs Sonnet vs Haiku spend mix      | LangSmith token usage           |
| **Referee block rate**          | Drift / abuse detector (sudden spike = something off)  | `RefereeReport.blocked` field   |
| **Empty-output rate**           | Pipeline produced final synthesis but no TRUE claims   | `compose_final` fallback path   |
| **Source diversity per lane**   | Are lanes degenerating to one outlet?                  | Per-run source list             |

## LangSmith dashboard queries

These queries assume the conventional LangSmith UI filter syntax —
adjust for your project setup.

```
# Slowest node in the last 24h
status:success run_type:chain
sort by latency_ms desc

# Referee blocks in the last 7d
status:success metadata.langgraph_node:referee
filter: output.referee_report.blocked = true

# Brave Search failures
status:error name:web_searcher

# Cost per query (USD) — group by query
metric: total_cost
group by: input.query
```

## Alerting (recommended)

Wire LangSmith webhooks to your alerting system for:

1. **`compose_final` failure rate > 5%** over a 1-hour window — backend
   degradation.
2. **Referee block rate spike** (>30% over a 1-hour window when the
   24h baseline is <10%) — likely prompt-injection campaign or
   upstream content shift.
3. **Brave Search HTTP 5xx rate > 10%** — upstream outage; degrade
   gracefully via cached responses if possible.
4. **OpenAI 429s** — rate limit hit; surfaces as `RetryError` in
   `llm.py`.

## Cost guardrails

The OpenAI token budget per request is bounded by:

- `OPENAI_MAX_OUTPUT_TOKENS` (default `1200`, can be overridden via
  env). Used by `llm.py` as `max_completion_tokens`.
- `llm.py` retries with `2x` and then a hard cap of
  `MAX_STRUCTURED_OUTPUT_RETRY_TOKENS = 16_384` when an output is
  truncated. Worst-case three calls per node × ~16k tokens output.

Use LangSmith's daily / monthly cost rollup to watch for cost drift.

## Local debugging

For runs that need richer instrumentation than logs but you don't want
to ship to LangSmith:

```bash
cd app
LOG_LEVEL=DEBUG uv run python -m geopoliticai.cli "your query" \
  --infosphere polish --report full
```

`generic_analyst.py`, `cross_check_facts.py`, and `compose_final.py`
emit DEBUG-level logs that mirror the LangSmith trace at a coarse
granularity.
