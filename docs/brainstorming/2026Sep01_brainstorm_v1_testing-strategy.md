# Testing Strategy

**Started:** 2026-09-01
**Status:** Complete
**Mode:** single-question rounds, closed with a final decision batch

## Target design

Build one deeply audited, local-only Phoenix offline evaluation around a controlled full-orchestrator journey for the Finland NATO case. Compare the current candidate with source baseline `f179453`, generate fresh production-model answers, and independently score usefulness and faithfulness. Keep the pilot observational, reproducible from Git-owned definitions, and portable to later CI without implementing GitHub Actions or live E2E yet.

## Context verified

- The application is a Python FastAPI and LangGraph service with an orchestrator graph, a nested geopolitical expert graph, Brave search, fetched article extraction, streamed LLM output, SSE delivery, and PostgreSQL-backed checkpoints in the API lifespan.
- Pytest collects 84 tests: 12 under `tests/integration_tests/` and 72 under `tests/unit_tests/` (including parameterized cases).
- Existing tests cover graph topology and streaming, node behavior, API validation and SSE frames, rate limiting, source-domain policy, search concurrency/error behavior, redirects and extraction, tracing, frontend source-level assertions, and error status mappings.
- The workflow named `Unit Tests` runs bare `uv run pytest`, so it includes both the unit and integration directories.
- There is no checked-in pytest timeout, coverage configuration, coverage dependency, real-browser suite, or explicit live-provider evaluation suite.
- The frontend promises "geopolitical analysis grounded in cross-spectrum reporting," and the expert prompt calls the model a geopolitical research analyst, but neither the frontend nor repository documentation identifies a target reader or expected level of expertise.
- No project-specific evaluation World Knowledge Skill or existing evaluation dataset was found.
- Phoenix's current client-side Evals SDK models every evaluator as structured `Score` output and supports LLM, code, and human score kinds; input mappings can bind repository-specific query, context, and output shapes.
- Phoenix recommends categorical labels over numeric ratings for most LLM evaluation tasks, provides deterministic code evaluators, supports synchronous and asynchronous dataframe batches, and records per-evaluator execution failures separately from scores.
- Phoenix experiments combine an uploaded dataset, a task function, evaluators, metadata, traces, and aggregate results; its experiments API supports repeated runs with a `repetitions` parameter.
- The Phoenix Evals library can run independently without a Phoenix server. Uploading datasets and experiments to Phoenix adds tracking and UI inspection but is not required for local execution.
- Phoenix's official custom-evaluator guidance recommends a labeled ground-truth set and measuring precision, recall, and F1 when calibrating an LLM evaluator. This conflicts with the settled choice to use judge self-agreement without human-reviewed verdicts.
- Phoenix documents experiment-level pairwise evaluation as an A/B workflow that compares two outputs side by side and retains preference plus qualitative feedback; the documented Python example uses a third-party pairwise evaluator, so this project would need a custom Phoenix classification evaluator for candidate/baseline/tie labels.
- Phoenix's prebuilt `FaithfulnessEvaluator` classifies whether an output is supported by and non-contradictory to supplied context, returning `faithful`/`unfaithful`, a binary score, an explanation, and model metadata. Phoenix recommends adapting its prompt for project-specific needs.
- No external documentation MCP server was exposed by this workspace; official Phoenix Markdown documentation was used instead.
- Official OpenAI documentation lists `gpt-4o-mini-2024-07-18` as the default and only named GPT-4o Mini snapshot, with structured-output support. This permits a pinned same-family judge while production answer generation continues using the moving `gpt-4o-mini` alias.
- The repository currently depends on `arize-phoenix-otel` for tracing but does not declare the Phoenix Evals SDK/client dependency needed for datasets and experiments. Compose already runs `arizephoenix/phoenix:version-20.4.0` and exposes it on loopback in development.
- The default branch is `main`, but the current feature branch adds the entire orchestrator. Therefore `main` cannot serve as a full-orchestrator baseline for the first Task without backporting the new harness architecture.
- A local baseline on Python 3.12.3 with pytest 9.0.2 passed the first seven collected tests and then hung for more than 80 seconds on `tests/integration_tests/test_orchestrator_graph.py::test_expert_branch_streams_namespaced_answer_tokens`; an isolated 20-second run of that test also timed out. CI declares Python 3.11.
- The worktree already contained user changes to `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, and `.codex/skills/grill-me/`; they were not modified by this session.

## Settled decisions

- **Primary confidence target and layers** — Prioritize real product quality through two layers: controlled offline evaluations as the main benchmark, plus a small scheduled live E2E smoke suite. _(rationale: the main investment should measure realistic complete agent behavior, while live checks separately detect provider and infrastructure drift)_
  - Challenged on: an offline evaluation can score a canned model response while bypassing Brave, fetching, PostgreSQL, SSE, and the browser, so “offline evaluation” and “end to end” are not automatically the same test → held, with the two boundaries explicitly separated.
  - Consequences: product-level scenarios and quality criteria come before coverage targets or a comprehensive unit-test cleanup; live dependency checks remain deliberately small and separately classified.
- **First offline benchmark quality** — Make overall answer usefulness the primary score, with basic grounding as a non-negotiable pass gate. _(rationale: the benchmark should measure whether the answer helps the user, while preventing polished unsupported answers from passing)_
  - Challenged on: an LLM judge can reward plausible unsupported analysis → revised to retain usefulness as primary while failing material invented facts, contradictions, or citations absent from the supplied evidence.
  - Consequences: the first benchmark needs a usefulness rubric and judge calibration plus a separate minimal grounding verifier; detailed citation-quality scoring can remain later work.
- **Primary reader and presentation** — Optimize for a generally informed reader and consistently concise briefings. _(rationale: the user explicitly prefers a predictable, focused briefing over question-dependent analytical depth)_
  - Challenged on: consistent concision can oversimplify broad geopolitical questions and conflict with answering at the length a question deserves → held.
  - Consequences: the usefulness rubric should reward prioritization and penalize unnecessary detail; an explicit size boundary remains to be defined without relying on exact wording.
- **Benchmark-case provenance and truth model** — Use a real geopolitical case with frozen sources, allow multiple evidence-supported interpretations, and use a human-reviewed evidence map for grounding rather than one golden answer. _(rationale: realistic user work matters more than exact synthetic truth, and geopolitical analysis legitimately permits different emphases)_
  - Challenged on: ambiguous real-world truth creates editorial cost and inconsistent judge scores → held, accepting the need for evidence mapping and judge calibration.
  - Consequences: each case needs a dated corpus, supported and prohibited claims, legitimate disagreements, and multiple known-good answer variants; usefulness prioritization is intentionally left to the LLM judge rather than encoded as required themes.
- **First case difficulty and prioritization** — Use information overload requiring concise prioritization, and let an LLM judge decide which supported material was most useful rather than enforcing human-authored indispensable themes. _(rationale: preserve multiple valid interpretations and avoid encoding one editor's preferred geopolitical narrative)_
  - Challenged on: without indispensable themes, importance is harder to verify reproducibly → revised from the lean; judge flexibility was preferred over a deterministic editorial checklist.
  - Consequences: the judge must receive the full bounded frozen corpus and a narrow usefulness rubric; calibration must measure verdict variance and include materially different valid briefings.
- **Usefulness judge execution and calibration** — Use one pinned judge call per evaluated answer and calibrate it by repeated self-agreement, without human-reviewed expected verdicts. _(rationale: avoid aggregation cost and avoid reintroducing human editorial judgment)_
  - Challenged on: self-agreement measures consistency rather than correctness and can validate a consistently biased or overly generous judge → held; this limitation is accepted.
  - Consequences: the usefulness result has no independent human anchor; model and rubric versions must still be recorded, and the score is stronger evidence of repeatability or regression than of absolute product quality.
- **Initial enforcement** — Launch as a non-blocking observational pilot with a time- or run-bounded mandatory review that must promote, revise, explicitly extend, or retire it. _(rationale: avoid blocking changes on an unvalidated self-calibrated judge while preventing an indefinitely ignored dashboard)_
  - Challenged on: non-blocking reports are easily ignored, while an artificial deadline can force a premature decision → held with an explicit review trigger and decision set.
  - Consequences: the implementation plan must name the trigger, retained evidence, reviewer/owner, and allowed review outcomes before the pilot starts.
- **Offline model execution boundary** — Generate fresh answers using the production answer-model configuration and fresh verdicts from the pinned judge; retain recorded outputs only for evaluator tests. _(rationale: measure the behavior users currently receive, including drift behind the production model configuration)_
  - Challenged on: a moving production model confounds repository regressions with provider drift → revised from the lean; user-facing fidelity was chosen over clean attribution.
  - Consequences: answer-model identifiers and settings must be recorded on every run, and absolute score changes cannot be attributed to code alone.
- **Evaluation framework and rollout location** — Use the Phoenix Evals SDK; run evaluations locally at first and design toward later GitHub Actions execution. _(rationale: explicitly required by the user)_
  - Challenged on: Phoenix's recommended labeled-ground-truth calibration conflicts with the selected judge self-calibration; local-only state can also become inaccessible to future GitHub Actions. Both compatibility decisions remain open.
  - Consequences: evaluators should emit Phoenix `Score` objects, local commands must not assume a hosted SaaS service, and dataset/result ownership must eventually support CI.
- **Phoenix calibration-policy exception** — Intentionally retain judge self-calibration instead of Phoenix's recommended human-labeled ground-truth calibration. _(rationale: the user continues to reject human-reviewed expected usefulness verdicts)_
  - Challenged on: self-agreement cannot establish evaluator correctness or support meaningful precision, recall, or F1 → held; only repeatability will be claimed.
  - Consequences: Phoenix repetitions can measure stability, but reports must not label the usefulness evaluator accurate or validated against human preference.
- **Regression and stability execution** — Compare candidate and baseline concurrently with one fresh trial per case, and measure judge self-agreement separately by repeatedly scoring fixed recorded answers. _(rationale: reduce routine local API cost while retaining a dedicated repeatability check)_
  - Challenged on: one matched pair leaves answer-generation variance unmeasured, and fixed-answer stability cannot repair that → held; generation variance is accepted during the non-blocking pilot.
  - Consequences: candidate/baseline differences are descriptive rather than statistically strong; the stability suite and real benchmark must be reported separately.
- **Evaluation ownership and frozen-source storage** — Git owns versioned benchmark definitions; Phoenix owns experiment runs and visualization. Git stores bounded source excerpts with title, publisher, URL, publication/retrieval dates, content hash, and truncation notes rather than complete commercial articles. _(rationale: make local and future CI inputs reproducible and reviewable without committing complete commercial reporting)_
  - Challenged on: excerpts weaken information overload and allow benchmark authors to preselect evidence → held; this reduced retrieval realism is accepted.
  - Consequences: dataset synchronization must be one-way from Git to Phoenix, case reviews must inspect excerpt selection, and the benchmark must not claim to test full-article selection.
- **Controlled offline harness and failure attribution** — Invoke the full orchestrator with frozen search/fetch adapters. Wrong routing and genuine agent/pipeline failures score zero; fixture, credential, Phoenix, and judge failures invalidate the run and receive no score. _(rationale: preserve full user-path accountability without mislabeling evaluation infrastructure failures as product failures)_
  - Challenged on: routing failures can dominate a benchmark intended to measure answer usefulness → held; full-pipeline product behavior takes precedence.
  - Consequences: task output and evaluators need explicit route, rewrite, source, answer, and execution-status evidence, not only final text.
- **Initial benchmark breadth and claim** — Prove one deeply audited Task before creating a family, and treat it only as validation of the evaluation system rather than evidence of broad GeopoliticAI quality. _(rationale: avoid multiplying harness and verifier defects or overgeneralizing from one topic)_
  - Challenged on: one Task delivers little general product evidence and invites topical overfitting → held; broad quality claims are explicitly deferred.
  - Consequences: completion criteria focus on environment fidelity, verifier behavior, trace evidence, known-good/wrong fixtures, and one real run; expansion is a later reviewed step.
- **First real Task question** — Use Finland's NATO decision and ask: "Why did Finland abandon military non-alignment after Russia's 2022 invasion, and why was its NATO accession completed only in April 2023?" _(rationale: retain a stable real case while making source use more observable through a cutoff-specific accession component)_
  - Challenged on: the second component complicates a concise briefing and may distract from the strategic cause → held.
  - Consequences: the frozen corpus and usefulness rubric must cover both strategic explanation and accession timing without requiring a long answer.
- **Usefulness verdict form and claim boundary** — Judge baseline and candidate independently with categorical `meets_usefulness_rubric` / `does_not_meet_usefulness_rubric` Phoenix scores, recording judge model, rubric version, and explanation. _(rationale: retain absolute per-answer reporting without presenting the self-calibrated judge as validated human preference)_
  - Challenged on: independent absolute thresholds are defined only by the unvalidated judge and may provide less directional signal than pairwise comparison → held with explicit judge-rubric naming.
  - Consequences: reports may compare label changes but must qualify them as automated rubric verdicts and retain both explanations.
- **First grounding gate** — Use Phoenix's prebuilt `FaithfulnessEvaluator` alone. Citation presence, exact URL copying, and claim-to-link placement remain outside the first Task's score. _(rationale: keep the first evaluation-system pilot small and centered on Phoenix's semantic grounding metric)_
  - Challenged on: an answer with supported prose but a fabricated URL can still pass faithfulness → held; citation compliance is deliberately deferred.
  - Consequences: reports must say `faithful_to_combined_context`, not `citation_valid`; no claim of full expert-prompt compliance is allowed.
- **Usefulness diagnostic output and aggregation** — One structured judge call returns criterion-level scores for answering both parts, general-reader clarity, prioritization, and concision, plus an independently judged overall verdict. _(rationale: preserve diagnostic detail while allowing the judge to weigh tradeoffs rather than applying strict all-or-nothing aggregation)_
  - Challenged on: the overall verdict can contradict a failed criterion and obscure the actual pass rule → held; explanations and every criterion must be retained to expose the tradeoff.
  - Consequences: no code-derived overall label; reports must display the breakdown beside the overall verdict and flag inconsistent combinations for inspection.
- **Judge model relationship and version** — Use the same GPT-4o Mini family as the production answer model, but pin the judge to `gpt-4o-mini-2024-07-18` while answers follow the `gpt-4o-mini` alias. _(rationale: lower cost and simpler setup while preventing judge drift)_
  - Challenged on: shared-family blind spots remain, and the pinned older judge may diverge from the moving production alias → held.
  - Consequences: every Phoenix score records the judge snapshot; every experiment records the resolved answer-model configuration; same-family does not imply same underlying version.
- **Phoenix-required boundary** — Real local experiments require the self-hosted Phoenix service and OpenAI access; fixture, mapping, parser, aggregation, and evaluator-boundary tests remain standalone. _(rationale: keep Phoenix as the experiment system of record without making deterministic component tests infrastructure-dependent)_
  - Challenged on: two commands and execution paths add complexity → held.
  - Consequences: readiness and credential failures invalidate real runs, while standalone tests must use fixed data and no network.
- **Initial source baseline** — Use application source from commit `f179453` as the first baseline while sharing the candidate's current versioned evaluation environment, dependencies, Phoenix SDK, fixtures, and external adapters. _(rationale: validate cross-revision execution without building a second historical environment)_
  - Challenged on: shared current dependencies mean this is not a pure historical reproduction → held.
  - Consequences: reports call it a source baseline, record both source and environment revisions, and do not attribute differences solely to historical runtime behavior.
- **Pilot review trigger** — Require review after ten valid candidate/baseline comparisons across at least three candidate revisions, with no calendar backstop. _(rationale: review should be based on accumulated experiment evidence rather than elapsed time)_
  - Challenged on: low local adoption can leave the pilot open forever → held; this risk is accepted.
  - Consequences: invalid runs do not count, and the pilot status must expose progress toward both thresholds.
- **First implementation boundary and interface** — Ship only the local offline evaluation, exposed through non-interactive, environment-driven commands with machine-readable JSON results and defined exit semantics. Do not add live E2E, browser tests, GitHub Actions, or placeholder scaffolding. _(rationale: validate the first Phoenix Task locally while preserving a low-friction path to later automation)_
  - Challenged on: designing a CI-compatible contract before observing local usage may introduce premature structure → held.
  - Consequences: the command must not require notebook interaction; credentials come from the environment; future CI should be able to call the same interface.
- **Native experiment architecture** — Use Phoenix-native datasets, experiments, Task execution, and evaluators rather than wrapping the workflow in Harbor. _(rationale: Phoenix is the explicitly selected experiment system and a second harness would add little to the first pilot)_
  - Challenged on: a Harbor wrapper could standardize broader benchmark packaging → held in favor of smaller scope.
  - Consequences: project Task specifications can retain the discipline of evaluation engineering, but the executable harness and run records are Phoenix-native.
- **Baseline process isolation** — Execute `f179453` and the candidate in separate subprocesses/checkouts while sharing the candidate's current evaluation environment, frozen evidence, and controlled adapters. _(rationale: avoid Python module-cache and process-global contamination between source revisions)_
  - Challenged on: temporary checkout management adds operational complexity → held.
  - Consequences: reports record source revisions and the shared environment revision; temporary source locations must be explicit and safely managed.
- **Pilot result and exit semantics** — A valid experiment exits successfully even when usefulness or faithfulness verdicts are poor; invalid infrastructure, credential, evaluator, or execution conditions exit nonzero. _(rationale: quality verdicts are observational during the non-blocking pilot)_
  - Challenged on: successful exit status can make poor quality easy to overlook → held; Phoenix and the JSON artifact remain the quality-reporting surfaces.
  - Consequences: machine-readable output must clearly distinguish valid poor-quality results, product failures scored as zero, and invalid runs with no score.
- **Judge-stability protocol** — Re-score four fixed fixtures—clear pass, clear fail, alternative-valid, and borderline—five times each, reporting agreement and label flips without an enforcement threshold. _(rationale: measure self-consistency without pretending to have human-grounded accuracy during the observational pilot)_
  - Challenged on: severe instability remains non-blocking → held.
  - Consequences: stability results are separate from real candidate/baseline generation and must not be presented as answer-model variance.
- **Pre-implementation review boundary** — Produce and explicitly review the complete Finland Task Spec and frozen-evidence package before implementation. _(rationale: excerpt selection materially determines the benchmark's meaning and validity)_
  - Challenged on: this adds another pause before executable learning → held.
  - Consequences: no evaluation implementation begins until the Task question, corpus excerpts, provenance, controlled adapter mapping, expected execution evidence, and verifier contract are reviewed together.
- **Existing-suite scope** — Keep diagnosis of the hanging orchestrator integration test and general pytest cleanup outside the first offline-evaluation implementation, recording both as follow-up work. _(rationale: protect the one-Task validation scope)_
  - Challenged on: the hang may impede reliable local development → held as a separate workstream.
  - Consequences: the evaluation implementation must not silently claim to repair or validate the existing deterministic suite.
- **Pilot ownership** — The repository maintainer running the local experiments owns the mandatory review after ten valid comparisons across at least three candidate revisions. _(rationale: an evidence trigger needs an accountable decision maker even before CI exists)_
  - Challenged on: ownership may change when automation is introduced → held for the local pilot and revisited with CI.
  - Consequences: the run ledger must make progress toward the trigger visible enough for the maintainer to act.

## Design tree

- **SETTLED — Primary confidence target: product quality first**
  - **SETTLED — Controlled offline evaluations are the main benchmark**
  - **SETTLED — Scheduled live E2E is a small second layer**
  - **SETTLED — First offline capability: usefulness with a grounding gate**
  - **SETTLED — Intended reader: generally informed person**
  - **SETTLED — Presentation: consistently concise briefing**
  - **SETTLED — Case provenance: real with frozen evidence cutoff**
  - **SETTLED — Truth model: evidence map with multiple valid framings**
  - **SETTLED — First case difficulty: information overload**
  - **SETTLED — Priority selection: LLM judge, no indispensable-theme checklist**
  - **SETTLED — Judge execution: one pinned call per answer**
  - **SETTLED — Calibration: judge self-agreement, no human verdict anchors**
  - **SETTLED — Enforcement: non-blocking pilot**
  - **SETTLED — Lifecycle: mandatory bounded review and disposition**
  - **SETTLED — Generation: fresh answer and judge calls**
  - **SETTLED — Answer model: follow production configuration**
  - **SETTLED — Judge model: pinned**
  - **SETTLED — Regression comparison: concurrent candidate and baseline**
  - **SETTLED — Real benchmark repetitions: one matched pair per case**
  - **SETTLED — Judge repeatability: separate repeated fixed-answer suite**
  - **SETTLED — Phoenix calibration policy: intentional self-agreement-only exception**
  - **SETTLED — Definitions: Git canonical, one-way synchronized to Phoenix**
  - **SETTLED — Runs and visualization: Phoenix**
  - **SETTLED — Frozen evidence: bounded excerpts with provenance**
  - **SETTLED — Harness: full controlled orchestrator**
  - **SETTLED — Failure attribution: agent zero, infrastructure invalid**
  - **SETTLED — Initial breadth: one deeply audited Task**
  - **SETTLED — Initial claim: evaluation-system validity only**
  - **SETTLED — First case: Finland's NATO decision and April 2023 timing**
  - **SETTLED — Usefulness form: independent categorical verdict per answer**
  - **SETTLED — Usefulness labels: explicit judge-rubric boundary**
  - **SETTLED — Grounding: Phoenix FaithfulnessEvaluator only**
  - **SETTLED — Citation compliance: outside first Task**
  - **SETTLED — Usefulness diagnostics: criterion-level structured scores**
  - **SETTLED — Overall verdict: independently judge-weighted tradeoff**
  - **SETTLED — Judge family: GPT-4o Mini, same as answer family**
  - **SETTLED — Judge version: `gpt-4o-mini-2024-07-18` snapshot**
  - **SETTLED — Phoenix required for real experiments**
  - **SETTLED — Eval component tests run standalone**
  - **SETTLED — Initial baseline source: `f179453`**
  - **SETTLED — Baseline environment: current candidate evaluation environment**
  - **SETTLED — Pilot review: 10 valid comparisons across 3 revisions**
  - **SETTLED — No calendar backstop**
  - **SETTLED — First implementation: local offline Phoenix Task only**
  - **SETTLED — Interface: non-interactive, environment-driven, JSON-producing command**
  - **SETTLED — Harness: Phoenix-native, without Harbor wrapping**
  - **SETTLED — Baseline isolation: separate subprocesses/checkouts**
  - **SETTLED — Exit semantics: quality observational; invalid execution nonzero**
  - **SETTLED — Stability suite: four fixtures, five repeats, report-only**
  - **SETTLED — Review boundary: Task Spec and evidence package before implementation**
  - **SETTLED — Pilot owner: repository maintainer running experiments**
  - **DEFERRED — Pull-request gate reliability**
    - Test taxonomy and markers
    - Timeouts, speed budget, and flake policy
    - Coverage or mutation-testing policy
  - **DEFERRED — Additional product-behavior confidence layers**
    - Live provider and infrastructure boundaries
    - Answer-quality and citation evaluations
    - Browser-level user journeys
  - **DEFERRED — Broader maintenance discipline**
    - Fixture and fake strategy
    - CI matrix and local commands
    - Ownership and failure triage

## Current frontier (open questions)

None. The brainstorming design is closed. The next artifact is the reviewed Finland Task Spec and frozen-evidence package; implementation remains gated on that review.

## Pruned or deferred branches

- Live-provider E2E smoke tests, browser journeys, and GitHub Actions are deferred until the local Phoenix Task proves the evaluation system.
- Citation presence, URL validity, and claim-to-citation placement are excluded from the first Task even though they remain production requirements.
- Harbor packaging is pruned from the first implementation in favor of a Phoenix-native harness.
- Human-labeled usefulness calibration, pairwise judging, judge ensembles, real-experiment repetitions, and enforced stability thresholds are excluded from this pilot.
- General pytest taxonomy, timeout policy, coverage policy, mutation testing, and the hanging orchestrator-test diagnosis remain separate follow-up work.
- Expansion beyond the Finland case requires review after the first deeply audited Task is proven.

## Carried as flags, not decisions

- The local hang may depend on Python or dependency-version differences from CI; diagnose it after the testing objective is settled.
- Authoritative framework documentation may be needed for decisions involving current pytest, LangGraph streaming/checkpoint testing, or LangSmith evaluation features.

## Round log

### Round 1 — Q1: What must the upgrade catch first?

Decide whether the first investment targets a trusted pull-request gate or real product behavior. For example, after changing `agents/orchestrator/graph.py`, one approach must return a deterministic pass/fail in roughly two minutes with no network or database; the other runs real or recorded geopolitical prompts and detects degraded sourcing or answer quality, accepting more runtime, cost, and variance.

Lean was a trustworthy pull-request gate first. The strongest counter-case was that mocked determinism can miss the failures users actually experience. **User answered:** Option B first, specifically E2E tests described as offline evaluations. **Pushed back on:** an offline evaluation is not necessarily end to end; it may score outputs while bypassing search, fetch, persistence, transport, and browser layers → the user held the product-quality priority and explicitly chose two layers: controlled offline evaluations as the main suite and a small scheduled live E2E smoke suite.

### Round 2 — Q2: What should the first offline benchmark prove?

Compared evidence fidelity with overall usefulness for a frozen-source geopolitical case. Lean was evidence fidelity because it supports relatively independent verification. **User answered:** overall answer usefulness. **Pushed back on:** an LLM judge can reward a polished, relevant answer containing unsupported analysis, producing a high score for behavior that violates the expert's core source-only contract → the user chose a basic grounding requirement, making usefulness primary but unsupported material a failure.

### Round 3 — Q3: Useful to whom?

Compared an accessible briefing for a generally informed reader with dense analysis for a policy/research professional. Lean was the generally informed reader because the public frontend accepts unrestricted questions. **User answered:** generally informed reader. **Pushed back on:** an accessibility rubric can accidentally reward short, shallow simplification and conflict with the prompt's requirement to answer at the length the question deserves → the user chose consistently concise briefings, accepting the simplification risk.

### Round 4 — Q4: Should the first case be real or synthetic?

Compared a real geopolitical question with frozen historical sources against a fictional but realistic dossier with exact hidden truth. Lean was a real frozen case because it resembles actual user traffic. **User answered:** real geopolitical case. **Pushed back on:** real geopolitics rarely has one indisputable best answer, so reference-answer grading can encode the benchmark author's preferred narrative; fair grading requires a reviewed evidence map and multiple acceptable framings → the user kept the real case and explicitly allowed multiple interpretations.

### Round 5 — Q5: What should make the first case hard?

Compared information overload requiring concise prioritization with materially conflicting reports requiring explicit uncertainty. Lean was information overload because it directly tests the chosen concise-briefing goal. **User answered:** too much information. **Pushed back on:** prioritization cannot be independently scored unless human editors label a small set of themes indispensable, which can encode their preferred narrative → the user rejected the checklist and chose an LLM judge to select what matters from the complete frozen corpus.

### Round 6 — Q6: How stable must the usefulness verdict be?

Compared one pinned, calibrated judge call with aggregating several judge verdicts. Lean was one call initially, adding aggregation only if measured variance requires it. **User answered:** one calibrated, pinned judge. **Pushed back on:** calibration is circular if the judge merely agrees with itself; meaningful calibration requires human-reviewed pass, fail, alternative-valid, and borderline fixtures → the user chose judge self-calibration, accepting that it measures consistency rather than correctness.

### Round 7 — Q7: Can the initial evaluation block changes?

Compared a non-blocking observational report with an immediate CI quality gate. Lean was non-blocking because the self-calibrated judge has not established absolute validity. **User answered:** begin as a non-blocking report. **Pushed back on:** non-blocking reports are commonly ignored unless the pilot has a named review trigger and a required next decision → the user accepted a time- or run-bounded pilot with a required review decision.

### Round 8 — Q8: Does offline still call the models?

Compared fresh production-model answer and judge calls over frozen evidence with scoring only recorded answer fixtures. Lean was fresh calls for actual benchmark runs, retaining fixtures only for evaluator tests. **User answered:** generate fresh answers. **Pushed back on:** a moving answer-model alias makes score changes impossible to attribute cleanly to code versus provider model drift → the user chose to follow the production answer model, accepting confounded attribution in exchange for observing current user-facing behavior.

### Round 9 — Q9: Compare against a concurrent baseline or history?

Compared running the candidate and baseline concurrently under the same current answer model with comparing candidate scores to historical runs. Lean was concurrent comparison because it better isolates repository changes. **User answered:** concurrent candidate and baseline. **Pushed back on:** one matched pair removes version drift but not answer-generation variance, so a single lucky or unlucky generation can look like a regression. The user did not answer the matched-trial challenge; instead, they required Phoenix Evals, local-only execution initially, and later GitHub Actions. Q9 is deferred until the Phoenix calibration contradiction is resolved.

### Round 10 — Q10: Follow Phoenix calibration guidance or keep self-calibration?

Phoenix's official recommendation for human-labeled evaluator ground truth conflicted with the settled self-calibration choice. Lean was to revise Q6 and follow Phoenix's recommendation. **User answered:** keep judge self-calibration. **Pushed back on:** consistency cannot establish correctness or produce meaningful precision, recall, or F1 → held, accepting that only repeatability will be claimed.

### Round 11 — Q11: How many Phoenix repetitions per case?

Compared one matched candidate/baseline trial per case with Phoenix `repetitions=3` for both revisions. Lean was three repetitions because measuring variance is a core pilot purpose. **User answered:** one matched trial. **Pushed back on:** one trial cannot measure the judge self-agreement selected earlier; a separate repeated evaluator-stability suite over fixed recorded answers is needed to reconcile the decisions → the user accepted the separate stability suite while retaining one real matched pair.

### Round 12 — Q12: Where is the evaluation source of truth?

Compared Git-owned benchmark definitions synchronized to Phoenix with a local Phoenix instance as the canonical dataset store. Lean was Git ownership because local and future GitHub Actions runs need reproducible inputs. **User answered:** Git owns definitions; Phoenix owns experiment runs and visualization. **Pushed back on:** committing complete frozen commercial-news articles can create copyright, repository-size, and redistribution problems → the user chose bounded excerpts with provenance, accepting reduced full-article realism.

### Round 13 — Q13: How much of the agent should the offline Task run?

Compared invoking the full orchestrator with controlled search/fetch adapters against calling answer generation directly with preassembled excerpts. Lean was the full orchestrator because the user requested E2E-style offline evaluation. **User answered:** full controlled orchestrator. **Pushed back on:** routing and pipeline failures can prevent any answer from reaching the usefulness judge, so failure attribution must distinguish product failure from invalid evaluation infrastructure → the user chose agent failures as zero-quality results and evaluation-infrastructure failures as invalid runs.

### Round 14 — Q14: Start with one case or a suite?

Compared proving one deeply audited real case before expansion with immediately building a five-case geopolitical suite. Lean was one Task first to avoid multiplying harness or evaluator defects. **User answered:** prove one complete Task before creating the family. **Pushed back on:** one topic can validate the evaluation system but cannot establish general geopolitical product quality → the user limited the first Task's claim to evaluation-system validity only.

### Round 15 — Q15: Which real case should prove the system?

Compared Finland's NATO decision with Germany's post-2022 reduction of Russian-energy dependence. Lean was Finland because it offers a stable cutoff and manageable evidence map. **User answered:** Finland's NATO decision. **Pushed back on:** the familiar narrative may be answerable from model memory without meaningful use of the frozen excerpts; a cutoff-specific accession-process component would make evidence use more observable → the user chose the sharpened two-part question.

### Round 16 — Q16: Absolute usefulness or pairwise preference?

Compared independent useful/not-useful classification for baseline and candidate with a direct candidate/baseline/tie preference. Lean was pairwise because the judge lacks human-calibrated absolute truth. **User answered:** judge each answer independently. **Pushed back on:** an absolute `useful` label from a self-calibrated judge is not validated user usefulness and must be reported as the pinned judge's rubric verdict → the user chose explicit `meets_usefulness_rubric` / `does_not_meet_usefulness_rubric` labels.

### Round 17 — Q17: What makes up the basic grounding gate?

Compared Phoenix's prebuilt Faithfulness evaluator alone with layering it beside deterministic exact-URL validation. Lean was the layered gate because exact URLs are a core expert-prompt requirement. **User answered:** Faithfulness evaluator only. **Pushed back on:** faithfulness over combined context cannot verify citation presence, exact URL copying, or whether a cited URL came from the supplied corpus → the user kept Faithfulness only and explicitly excluded citation compliance from the first Task.

### Round 18 — Q18: One usefulness label or a diagnostic breakdown?

Compared one overall categorical usefulness verdict with criterion-level categorical scores plus the overall verdict from one structured judge call. Lean was the diagnostic breakdown for failure analysis. **User answered:** several scores from one structured response. **Pushed back on:** an independently judged overall label can contradict its own criterion scores; aggregation semantics must be explicit → the user chose to let the judge decide the overall verdict separately and preserve tradeoffs.

### Round 19 — Q19: Should the judge be independent of the answer model?

Compared the same model family as the production answer model with a distinct stronger pinned judge. Lean was the distinct stronger model to reduce direct self-evaluation bias. **User answered:** same model family. **Pushed back on:** same-family judging shares stylistic and reasoning blind spots; additionally, the moving answer alias and pinned-judge requirement need separate identifiers. Official OpenAI documentation confirms `gpt-4o-mini-2024-07-18` is available as a snapshot → the user chose to pin only the judge snapshot while the answer follows production.

### Round 20 — Q20: Must local Phoenix be running?

Compared requiring the self-hosted Phoenix service for local evaluation with allowing standalone execution and optional synchronization. Lean was Phoenix-required for the first experiment workflow. **User answered:** require Phoenix for the first implementation. **Pushed back on:** coupling every evaluator test to Phoenix would make fast deterministic validation infrastructure-dependent; only real experiments should require the service → the user required Phoenix only for real experiments and kept evaluator-component tests standalone.

### Round 21 — Q21: How does the first baseline get created?

Compared using current orchestrator commit `f179453` as the pre-evaluation baseline with making the first accepted evaluation implementation the baseline for later work. Lean was `f179453` to validate comparison machinery immediately. **User answered:** use `f179453`. **Pushed back on:** the commit lacks the evaluation dependencies and harness, so the design must choose between historical application source under the candidate environment and a complete historical environment → the user chose historical application source under the current versioned evaluation environment.

### Round 22 — Q22: What triggers the pilot review?

Compared an evidence-count review trigger with a fixed calendar deadline. Lean was ten valid paired comparisons across at least three revisions. **User answered:** evidence-count trigger. **Pushed back on:** local non-blocking use may never accumulate enough comparisons, leaving the pilot open indefinitely; a calendar backstop could force a disposition → the user rejected the calendar backstop and retained evidence-only review.

### Round 23 — Q23: What ships in the first implementation?

Compared a local offline Phoenix Task only with also implementing live E2E smoke tests and GitHub Actions. Lean was local-only to validate the first Task before expanding. **User answered:** local offline evaluation only. **Pushed back on:** an interactive or notebook-specific design could make later CI migration a rewrite; in the final batch, the user accepted a non-interactive CLI and machine-readable result contract without shipping a workflow.

### Final decision batch — Q23 through Q31

At the user's request, the remaining challenges were presented together rather than one question at a time. **User accepted every recommendation.** The first implementation is therefore local-only but exposes a non-interactive, environment-driven, machine-readable command contract; uses Phoenix directly rather than Harbor; isolates baseline and candidate in separate subprocesses/checkouts; treats valid poor-quality outcomes as successful observational runs and invalid evaluation execution as nonzero; measures judge stability with four fixed fixture classes repeated five times without a gate; requires explicit review of the Finland Task Spec and frozen corpus before implementation; leaves the hanging deterministic test and broader cleanup outside scope; adds no live/CI scaffolding; and assigns the evidence-triggered pilot review to the repository maintainer running the experiments.
