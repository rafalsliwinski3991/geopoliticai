# Basic expert and orchestrator evaluation

**Started:** 2026-09-02
**Status:** Complete
**Mode:** batch

## Target design

Delete the incomplete `app/evals/` pilot and replace it with one direct,
manually invoked Phoenix smoke-check runner under `app/tests/manual_quality/`.
The runner records two separate, overlapping live end-to-end experiments:

1. **Expert quality** runs the expert graph for: “Why did Finland abandon
   military non-alignment after Russia's full-scale invasion of Ukraine, and
   why did it become a NATO member in April 2023?” It records 1–5
   `groundedness` (including correct inline source links) and 1–5
   `usefulness`, each with a judge explanation.
2. **Orchestrator quality** supplies the history “Why did Finland become a
   NATO member in 2023?” → a short accession summary → “What about Sweden?”
   and runs the full orchestrator graph. It records exact `route_correct`
   (`geopolitical` required) and 1–5 `rewrite_quality` with an explanation.

The runner uses the pinned `gpt-4o-mini-2024-07-18` judge, one run per case,
and produces advisory reviewer evidence only—never a CI gate, pass-rate trend,
or release claim. Live search, fetch, model, judge, or Phoenix failures are
invalid and unscored. Results and normal unredacted auto-traces persist in
Phoenix; this intentionally includes fetched source text.

## Context verified

- `app/evals/` contains frozen-corpus loading and integrity checks only; it
  has no evaluator, controlled adapter, experiment runner, report, or Phoenix
  upload path.
- The Finland NATO task specification remains marked `Review gate pending`.
- The existing unit and integration tests already cover graph structure,
  routing, streaming, retrieval-node behaviour, and nested-expert invocation.
- The local Phoenix server is unavailable and there are no traces or
  experiments to derive a judge rubric from.
- Both graph modules initialize unredacted Phoenix tracing at import when
  `PHOENIX_COLLECTOR_ENDPOINT` is set; Compose sets that endpoint.

## Settled decisions

- **Scope** — Remove the old code, tests, corpus, task spec, and pilot plan;
  retain this completed design record. Phoenix dependencies remain because the
  replacement uses Phoenix experiments.
- **Execution** — A test-only runner invokes two live end-to-end experiments
  once each, manually. It is excluded from CI and runtime images.
- **Signals** — Expert: 1–5 groundedness (support plus inline links) and
  usefulness. Orchestrator: exact route boolean plus 1–5 rewrite quality.
  Every LLM score includes an explanation and is advisory only.
- **Judge** — `gpt-4o-mini-2024-07-18`, a low-cost pinned reviewer aid. Its
  shared family/tier with the app is an accepted limitation.
- **Data and failure policy** — Retain normal raw Phoenix traces, including
  fetched article text. A search, fetch, model, judge, or Phoenix failure
  invalidates the run and produces no score.
- **Known limits** — The cases are curated, stable, one-shot smoke checks;
  they do not support trend, comparison, coverage, or independent-quality
  claims. The two live experiments overlap and do not isolate faults.

## Design tree

- **Scope, runner, and persistence** — SETTLED
- **Live experiment boundaries and invalid-run semantics** — SETTLED
- **Cases, signals, score anchors, and judge** — SETTLED
- **Retention and raw tracing** — SETTLED

## Current frontier (open questions)

None.

## Carried as flags, not decisions

- Revisit the rubric and grow beyond one case per experiment only after a human
  reviews real smoke-check outputs; do not treat a score change as a trend.

## Round log

### Round 1 — Q1: Primary purpose

User requested batch mode before answering. The current frontier contained
only this prerequisite; the expert/orchestrator contracts and execution
boundary remained blocked until it was settled.

**User answered:** B — model-quality monitoring. **Pushed back on:** this
creates recurring API cost and nondeterministic results before the team has
traces or a human-calibrated definition of quality. Awaiting confirmation or
revision.

**User held:** yes. Decision settled.

**User held:** yes. The curated, focused, manual baseline is settled.

### Round 3 — Q5–Q7: What the judges measure

**User answered:** expert groundedness and usefulness separately;
orchestrator route plus rewrite; advisory human-reviewed report. **Pushed back
on:** without fixed rubrics and known good/bad review examples, these subjective
signals can become incomparable opinions and the absence of a threshold makes
them easy to rationalize. Awaiting confirmation or revision.

**User held:** yes. Decisions settled.

### Round 6 — Q14–Q16: What each Phoenix experiment exercises

**User answered:** live Brave expert; full live orchestrator; separate Phoenix
experiments. **Pushed back on:** the full orchestrator invokes the full expert,
so the two experiments overlap on live search, fetching, and answer generation.
This contradicts the earlier settled choice of focused, separately diagnosable
evaluations and also duplicates cost/data. Awaiting clarification: revise the
focused-boundary decision or revise these live boundaries.

### Round 7 — Conflict resolution: focused ownership versus production realism

**User answered:** A — prefer production realism. The previous focused
evaluation decision is reopened and replaced by two separate, overlapping live
end-to-end experiments. **Pushed back on:** one transient Brave/search/fetch
failure or a changing article can make a score impossible to attribute, while
the two runs duplicate external cost and Phoenix-held data. Awaiting
confirmation or revision.

**User held:** yes. The revised live, overlapping experiment boundaries and
separate Phoenix grouping are settled.

### Round 8 — Q17–Q19: Live-run safety and noise

**User answered:** invalid unscored external failures; one run per case;
Phoenix retains question, answer, scores, explanation, URLs, and source hashes
but not article bodies. **Pushed back on:** a single numeric score over changing
web inputs cannot establish a quality change; it is only a point-in-time
snapshot. Awaiting confirmation or revision.

**User held:** yes. Decisions settled as a point-in-time smoke-check.

### Round 9 — Q20–Q23: Prompts and rubric shape

**User answered:** user-supplied cases; full 1–5 anchors; separate route and
rewrite scores; stronger pinned judge. **Pushed back on:** the resulting judge
prompt will be more detailed than the two-case suite itself, and Q20 remains
underspecified until the exact production-concern transcripts are supplied.
Awaiting the strings and confirmation or revision.

**User held:** yes for the anchored, split, stronger-model rubric. Those
decisions are settled. The exact Q20 transcripts remain required and open;
the user's confirmation did not provide strings to evaluate.

### Round 10 — Q20: Exact curated transcripts

**User supplied:** expert query `Why FInland join the Nato in 2023`; orchestrator
conversation `Why Finland join the warsaw Pact in 2023` → `Did you mean NATO`
→ `yesr`. **Pushed back on:** the latter's false premise, correction, and typo
may make it a test of ambiguity repair and classifier policy rather than the
ordinary routing/rewrite behaviour the suite claims to measure. Awaiting
confirmation or revision.

**User redirected:** asked for a codebase-grounded proposal rather than
confirmation of the supplied text. Inspection verified that the classifier
prompt explicitly requires self-contained rewriting and resolving ellipses
from history, while it requires preserving meaning rather than correcting
false premises. A proposed replacement pair is now the active Q20 decision.

### Round 11 — Q20: Proposed codebase-aligned pair

**User answered:** A — use the proposed Finland expert and Sweden follow-up
pair. **Pushed back on:** this is a stable, familiar topic and can be easier
than the ambiguous or fast-moving questions users may actually bring. Awaiting
confirmation or revision.

**User held:** yes. The pair is settled as the deliberately simple first case.

### Round 12 — Q24–Q25: Judge and command

**User answered:** `gpt4 mini or something else which is free`; test-only
runner. **Pushed back on:** official OpenAI documentation lists the API free
tier as unsupported for `gpt-4o-mini`, whose dated snapshot is
`gpt-4o-mini-2024-07-18` and whose text price is $0.15 input / $0.60 output per
million tokens. The desired zero-cost judge conflicts with live OpenAI and
Brave system runs, the stronger-judge decision, and Phoenix experiments.
Awaiting clarification. Q25 awaits confirmation after this shared cost
challenge.

### Round 13 — Q24: Judge-cost boundary clarified

**User answered:** B — lowest-cost paid pinned judge. The judge is
`gpt-4o-mini-2024-07-18`. **Pushed back on:** it is the same model family/tier
as the application and can share its reasoning and style blind spots; it does
not satisfy the earlier stronger-judge decision. Awaiting confirmation or
revision, together with the chosen test-only runner.

**User held:** yes. Q24 and Q25 are settled as a low-cost reviewer aid and
direct, test-only runner.

### Round 14 — Q26: Tracing versus source retention

Codebase inspection verified that both graph modules call `init_tracing()` at
import time. When `PHOENIX_COLLECTOR_ENDPOINT` is set, `tracing.py` registers
auto-instrumentation without a masking `TraceConfig`; Compose sets that
endpoint. Consequently a live expert prompt containing fetched article text is
exported to Phoenix, contradicting the selected no-article-body retention
policy. Awaiting a retention decision.

**User answered:** C — accept raw source text in Phoenix traces. **Pushed back
on:** this reverses the selected reduced-retention boundary and makes the
Phoenix volume a persistent store of third-party article text, user queries,
answers, and judge material. Awaiting confirmation or revision.

**User held:** yes. Raw automatic traces are retained for the manual runner.

### Round 15 — Q27–Q28: Final score boundary and cleanup

**User answered:** citations inside groundedness; clean-cut removal of obsolete
pilot artifacts. **Pushed back on:** citations and factual support become one
score, while deletion loses the detailed former plan/task-spec archaeology.
Awaiting confirmation or revision.

**User held:** yes. Decisions settled.

### Round 16 — Q29: Numeric route score versus exact contract

Post-decision code inspection found that `Destination` is
`Literal["geopolitical", "other"]`, and the classifier's structured output is
validated as that type. For the selected Sweden follow-up the expected route is
therefore an exact code predicate, not a degree of quality. A numeric LLM judge
would create noise without measuring additional route behaviour. Awaiting the
implementation decision.

**User answered:** A — code-check route correctness and numerically judge only
rewrite quality. **Pushed back on:** the two orchestrator outputs have different
shapes, which adds a small dashboard special case. Awaiting confirmation or
revision.

**User clarified:** keep the mixed shape for now. Decision settled.

### Round 17 — Q30: Exact score-anchor text

**User answered:** A — approve the proposed anchored rubric. **Pushed back
on:** one case per experiment cannot validate that the 1–5 boundaries match
human judgment. Awaiting confirmation or revision.

**User held:** yes. The rubric is settled as an uncalibrated reviewer aid.

### Round 4 — Q8–Q10: Comparable signals

**User answered:** one case per focused evaluation; numeric score plus
explanation; separate pinned judge model. **Pushed back on:** two outputs and
a subjective numeric scale cannot distinguish product movement from prompt or
judge noise, even with a pinned judge. Awaiting confirmation or revision.

**User held:** yes. Decisions settled as a smoke signal, not a comparison
metric.

### Round 5 — Q11–Q13: Smallest implementation shape

**User answered:** Phoenix experiment; Python case constants; upload results to
Phoenix. **Pushed back on:** this makes Phoenix availability, credentials,
dependencies, and data retention prerequisites of a two-case smoke signal,
reintroducing much of the dependency surface being removed. Awaiting
confirmation or revision.

**User held:** yes. Decisions settled.

### Round 2 — Q2–Q4: Inputs, coverage, and operating cost

**User answered:** curated scenarios; two focused evaluations; manual command
only. **Pushed back on:** the combined choice deliberately omits production
traffic, end-to-end behaviour, and automatic execution, so a regression in
live-search integration could go unseen indefinitely. Awaiting confirmation
or revision.
