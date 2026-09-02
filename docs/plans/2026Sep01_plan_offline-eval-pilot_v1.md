# Plan — Local offline Phoenix evaluation pilot (Finland NATO Task)

**Source brainstorm:** `docs/brainstorming/2026Sep01_brainstorm_v1_testing-strategy.md`
**Repo state planned against:** `28cef6b` on branch `2026Aug29-develop-the-app`
**Status:** draft for implementation, gated on the Commit 3 review

---

## 1. Scope summary

### What is added

A new, non-shipped `app/evals/` package that runs one Phoenix experiment: the full
orchestrator graph over a Git-owned frozen evidence corpus for one Finland/NATO
question, executed once for the candidate revision and once for source baseline
`f179453`, scored by a pinned `gpt-4o-mini-2024-07-18` usefulness judge and Phoenix's
prebuilt `FaithfulnessEvaluator`, with a machine-readable JSON artifact and defined
exit semantics. Plus a separate judge-stability command (4 fixtures × 5 repeats).

### What is deleted

Nothing. This plan is purely additive to application code. No existing test is
rewritten or removed.

### What is deliberately kept, and on whose rationale

| Kept as-is | Rationale (brainstorm decision) |
| --- | --- |
| The hanging `tests/integration_tests/test_orchestrator_graph.py::test_expert_branch_streams_namespaced_answer_tokens` | *Existing-suite scope* — diagnosis is a separate workstream; this plan must not claim to repair it |
| No pytest markers, timeouts, coverage config, or taxonomy | *Existing-suite scope* — deferred |
| No GitHub Actions workflow, no live E2E, no browser tests | *First implementation boundary* — local only |
| No Harbor wrapper | *Native experiment architecture* |
| Citation presence / exact-URL / claim placement scoring | *First grounding gate* — explicitly out of the first Task |
| Human-labeled judge calibration, pairwise judging, judge ensembles, `repetitions>1` on the real benchmark | *Phoenix calibration-policy exception*, *Regression and stability execution* |
| Production answer model stays the moving `gpt-4o-mini` alias | *Offline model execution boundary* |
| `src/` untouched | The controlled adapters attach at an existing import seam; the baseline revision must run unmodified source |

### Where the brainstorm and the code disagree

These are recorded as findings, not silently corrected:

1. **`f179453` is byte-identical to `HEAD` for `app/src/`.** The brainstorm calls it
   "the pre-evaluation baseline" and Round 21 calls it "current orchestrator commit
   `f179453`". `git diff --stat f179453 HEAD -- app/src app/pyproject.toml` is empty:
   `f179453` ("update the opencode plugin") only touched tooling files. The first
   comparison therefore compares *identical application source*. That is still a
   useful first run — it validates the comparison machinery and gives a
   generation-plus-judge noise floor — but the plan must not, and the reports must
   not, present a candidate/baseline delta from run 1 as a code effect. This is
   named in `--help`, in the report artifact (`"source_diff": "empty"`), and in the
   ledger.
2. **The brainstorm's "84 collected tests" is stale in shape, not in count.** Current
   layout is 12 integration + 72 unit as described; no change needed.
3. **`app/pyproject.toml` has no `[tool.pytest.ini_options]` at all**, and
   `app/tests/` has no `__init__.py`, so pytest inserts `app/tests` (not `app/`) on
   `sys.path`. A package at `app/evals/` is therefore *not* importable from tests
   without adding `pythonpath = ["."]`. The brainstorm defers "pytest configuration",
   but it deferred *policy* (markers, timeouts, coverage), not the minimum wiring a
   new package needs. Commit 1 adds exactly the `pythonpath` line and nothing else.
4. **The brainstorm says the repo "does not declare the Phoenix Evals SDK".** Correct.
   It also needs `arize-phoenix-client` — `phoenix.evals` alone has no datasets or
   experiments. Both go in the `dev` dependency group (see Commit 1 rationale).
5. **Phoenix's own `wrap_phoenix_evals_evaluator` keeps only `scores[0]`.**
   `phoenix/client/resources/experiments/evaluators.py:264-276` returns
   `_score_to_experiment_evaluation(scores[0])` when a `phoenix.evals` evaluator is
   passed straight to `run_experiment`. The settled "criterion-level scores from one
   structured judge call" therefore *cannot* be delivered by handing the judge object
   to `evaluators=[...]`; it must go through the client's own
   `create_evaluator` decorator on a plain function that returns the full
   `list[Score]`. Commit 4 and Commit 7 are built on that.

---

## 2. Ordered commits

Ten commits. Commits 1–3 are definitional and carry the mandatory review gate.
Commits 4–5 are pure, network-free evaluator code. Commit 6 is the riskiest piece
(subprocess + worktree + adapter interposition) and lands only after everything it
depends on is proven. Commits 7–9 wire Phoenix and the CLI. Commit 10 syncs guidance.

Every commit must leave `uv run pytest tests/unit_tests` green. `make lint` runs
`mypy --strict` over `.` when invoked as `make lint`, so every new module is fully
annotated and carries Google-style docstrings (ruff `D` is on, `tests/*` is exempt).

> **Baseline note for every test command below:** run the unit directory
> explicitly. `uv run pytest` (bare) also collects `tests/integration_tests`, which
> contains a test that hangs locally on Python 3.12 (brainstorm, "Context verified").
> That hang is out of scope and must not be mistaken for a regression from this work.
> Before starting, record the pre-existing state:
> `uv run pytest tests/unit_tests -q` → expect 72 passed.

---

### Commit 1 — Evaluation dependencies and package skeleton

**Files:** `app/pyproject.toml`, `app/uv.lock`, `app/evals/__init__.py`,
`app/evals/errors.py`, `app/tests/unit_tests/evals/__init__.py`,
`app/tests/unit_tests/evals/test_errors.py`

**Why safe here:** adds dependencies and one dependency-free module. No application
code path changes. The Docker image is unaffected because `app/Dockerfile` copies
only `src/` and runs `uv sync --frozen --no-dev`.

`app/pyproject.toml` — before:

```toml
[dependency-groups]
dev = [
    "anyio>=4.7.0",
    "langgraph-cli[inmem]>=0.4.14",
    "mypy>=1.13.0",
    "pytest>=8.3.5",
    "ruff>=0.8.2",
]
```

after:

```toml
[dependency-groups]
dev = [
    "anyio>=4.7.0",
    "langgraph-cli[inmem]>=0.4.14",
    "mypy>=1.13.0",
    "pytest>=8.3.5",
    "ruff>=0.8.2",
    # Offline evaluation pilot (evals/). These live in `dev`, not in a group of
    # their own: `app/Dockerfile` runs `uv sync --frozen --no-dev`, so `dev` is
    # the one group guaranteed to stay out of the runtime image, while CI's
    # `uv sync --locked --dev` still installs what the standalone evaluator
    # component tests import. Versions track the Phoenix server Compose runs
    # (arizephoenix/phoenix:version-20.4.0, which pins
    # arize-phoenix-client>=3.2.0 and arize-phoenix-evals>=3.5.1).
    "arize-phoenix-client>=3.3,<4.0",
    "arize-phoenix-evals>=3.5.1,<4.0",
]
```

and, appended:

```toml
[tool.pytest.ini_options]
# `app/tests/` has no __init__.py, so pytest inserts `app/tests` on sys.path,
# not `app/`. The application modules are importable because `uv sync` installs
# the project (a .pth pointing at app/src); `evals/` is not installed on
# purpose — it must never reach the runtime image — so it needs this line.
pythonpath = ["."]
```

`app/evals/__init__.py`:

```python
"""Local offline evaluation harness. Never imported by application code.

This package is deliberately outside `src/`: `app/Dockerfile` copies only
`src/`, so nothing here can reach the runtime image. The import direction is
one-way — `evals` may import `models`, `config`, and `agents`; nothing under
`src/` may ever import `evals`.
"""
```

`app/evals/errors.py`:

```python
"""The one distinction this harness exists to keep straight.

`InvalidRunError` means the *evaluation system* failed: a missing credential,
an unreachable Phoenix, a corpus whose hash no longer matches, a judge call
that raised. An invalid run produces no score and exits nonzero.

A product failure — a `PipelineError` from the agent, or a turn routed to the
wrong branch — is not an error here. It is a valid observation that scores
zero, and the command still exits successfully (brainstorm: "Controlled
offline harness and failure attribution", "Pilot result and exit semantics").
"""

from __future__ import annotations


class InvalidRunError(RuntimeError):
    """The evaluation could not be trusted; no score may be reported."""
```

Test (`app/tests/unit_tests/evals/test_errors.py`):

```python
import pytest

from evals.errors import InvalidRunError


def test_invalid_run_error_is_not_a_pipeline_error() -> None:
    from models import PipelineError

    assert not issubclass(InvalidRunError, PipelineError)
    with pytest.raises(InvalidRunError):
        raise InvalidRunError("phoenix unreachable")
```

**Gate:**

```bash
cd app && uv sync --locked --dev && uv run pytest tests/unit_tests -q
```

(`uv sync` will rewrite `uv.lock`; commit it. If `--locked` refuses, run
`uv lock` first and commit the lockfile in the same commit — CI uses
`uv sync --locked --dev` and fails on a stale lock.)

---

### Commit 2 — Frozen-corpus format, loader, and hash verification

**Files:** `app/evals/corpus.py`, `app/evals/cases/__init__.py`,
`app/tests/unit_tests/evals/test_corpus.py`,
`app/tests/unit_tests/evals/fixtures/synthetic_case/case.json`,
`app/tests/unit_tests/evals/fixtures/synthetic_case/corpus/*.json`

**Why safe here:** pure file IO plus hashing. No network, no model, no Phoenix.
The synthetic fixture case is clearly named and is never the benchmark.

`app/evals/corpus.py`:

```python
"""Frozen evidence: bounded excerpts that Git owns and Phoenix only mirrors.

Each excerpt is a JSON file carrying provenance (title, publisher, URL,
publication and retrieval dates, a truncation note) and the excerpt text.
`corpus.lock.json` records a SHA-256 per excerpt plus a corpus-level digest;
every load verifies them, and a mismatch is an `InvalidRunError`, never a
score. That is what makes "reproducible from Git-owned definitions" checkable
rather than aspirational.

Excerpts are bounded on purpose (brainstorm: "Evaluation ownership and
frozen-source storage"): this repository does not redistribute complete
commercial articles, and the benchmark therefore does not test full-article
selection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.errors import InvalidRunError
from models import Source

CASES_ROOT = Path(__file__).resolve().parent / "cases"
CORPUS_LOCK_NAME = "corpus.lock.json"
CASE_NAME = "case.json"


@dataclass(frozen=True)
class Excerpt:
    """One bounded, provenance-carrying source excerpt."""

    excerpt_id: str
    title: str
    url: str
    domain: str
    publisher: str
    published_at: str
    retrieved_at: str
    truncation_note: str
    text: str

    def as_source(self) -> Source:
        """Return this excerpt as the `Source` the fetch boundary would return."""
        return Source(title=self.title, url=self.url, text=self.text)

    def digest(self) -> str:
        """Return the SHA-256 of the excerpt text, as stored in the lock file."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Case:
    """One benchmark case: a question, an expected route, and frozen evidence."""

    case_id: str
    question: str
    expected_destination: str
    rubric_version: str
    corpus_digest: str
    excerpts: tuple[Excerpt, ...]

    @property
    def sources(self) -> list[Source]:
        """Return every excerpt as a `Source`, in corpus order."""
        return [excerpt.as_source() for excerpt in self.excerpts]


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object, or fail the run."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidRunError(f"Unreadable evaluation definition: {path}") from exc
    if not isinstance(payload, dict):
        raise InvalidRunError(f"Evaluation definition is not an object: {path}")
    return payload


def corpus_digest(excerpts: tuple[Excerpt, ...]) -> str:
    """Return the corpus-level digest: SHA-256 over sorted per-excerpt digests."""
    joined = "\n".join(
        f"{excerpt.excerpt_id}:{excerpt.digest()}"
        for excerpt in sorted(excerpts, key=lambda item: item.excerpt_id)
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def load_case(case_id: str, *, root: Path | None = None) -> Case:
    """Load and hash-verify one case. Any inconsistency invalidates the run."""
    case_dir = (root or CASES_ROOT) / case_id
    case_payload = _read_json(case_dir / CASE_NAME)
    lock_payload = _read_json(case_dir / CORPUS_LOCK_NAME)
    locked: dict[str, str] = dict(lock_payload.get("excerpts", {}))

    excerpts: list[Excerpt] = []
    for path in sorted((case_dir / "corpus").glob("*.json")):
        raw = _read_json(path)
        excerpt = Excerpt(
            excerpt_id=str(raw["excerpt_id"]),
            title=str(raw["title"]),
            url=str(raw["url"]),
            domain=str(raw["domain"]),
            publisher=str(raw["publisher"]),
            published_at=str(raw["published_at"]),
            retrieved_at=str(raw["retrieved_at"]),
            truncation_note=str(raw["truncation_note"]),
            text=str(raw["text"]),
        )
        expected = locked.get(excerpt.excerpt_id)
        if expected is None:
            raise InvalidRunError(f"Excerpt not in {CORPUS_LOCK_NAME}: {excerpt.excerpt_id}")
        if expected != excerpt.digest():
            raise InvalidRunError(
                f"Excerpt text changed since it was frozen: {excerpt.excerpt_id}"
            )
        excerpts.append(excerpt)

    if len(excerpts) != len(locked):
        raise InvalidRunError(
            f"{CORPUS_LOCK_NAME} lists {len(locked)} excerpts; {len(excerpts)} files found."
        )
    frozen = tuple(excerpts)
    digest = corpus_digest(frozen)
    if digest != str(lock_payload.get("corpus_digest", "")):
        raise InvalidRunError("Corpus digest does not match the lock file.")

    return Case(
        case_id=case_id,
        question=str(case_payload["question"]),
        expected_destination=str(case_payload["expected_destination"]),
        rubric_version=str(case_payload["rubric_version"]),
        corpus_digest=digest,
        excerpts=frozen,
    )


def combined_context(case: Case) -> str:
    """Render the whole corpus as the judge's and grounder's single context.

    Deliberately the *entire* bounded corpus, not the sources the agent chose:
    the settled design gives the judge the full frozen corpus and lets it decide
    what mattered, and `faithful_to_combined_context` is named after exactly
    this string.
    """
    return "\n\n".join(
        f"--- SOURCE ---\nTitle: {excerpt.title}\nURL: {excerpt.url}\n\n{excerpt.text}"
        for excerpt in case.excerpts
    )
```

`app/evals/cases/__init__.py` is an empty docstring-only module so `cases/` is a
package directory that ruff/mypy see.

Tests assert: a clean synthetic case loads with the expected excerpt count and
digest; mutating one fixture excerpt's text in a `tmp_path` copy raises
`InvalidRunError`; deleting an excerpt file raises `InvalidRunError`; an excerpt
absent from the lock raises; `combined_context` contains every URL exactly once;
`as_source()` produces a `models.Source`.

**Gate:** `cd app && uv run pytest tests/unit_tests/evals -q`

---

### Commit 3 — The Finland Task Spec and the real frozen corpus — **REVIEW GATE**

**Files:** `docs/evals/2026Sep01_task-spec_finland-nato.md`,
`app/evals/cases/finland_nato/case.json`,
`app/evals/cases/finland_nato/corpus/*.json`,
`app/evals/cases/finland_nato/corpus.lock.json`,
`app/evals/tools/freeze_corpus.py`

**Why this is its own commit and why everything stops here:** the settled
*Pre-implementation review boundary* says no evaluation implementation begins
until the question, corpus excerpts, provenance, adapter mapping, expected
execution evidence, and verifier contract are reviewed *together*. Excerpt
selection is what the benchmark actually means.

**Non-negotiable sourcing rule.** The excerpt text must be transcribed from real
articles on the expert's allow-listed domains
(`app/src/agents/expert/consts/sources.py`). No excerpt may be written, summarized,
paraphrased, or reconstructed from model memory. An invented corpus would make
every downstream number meaningless while looking exactly like a working
benchmark. `freeze_corpus.py` is a small maintainer utility that recomputes
`corpus.lock.json` from the excerpt files; it does not fetch anything.

`case.json`:

```json
{
  "case_id": "finland_nato",
  "question": "Why did Finland abandon military non-alignment after Russia's 2022 invasion, and why was its NATO accession completed only in April 2023?",
  "expected_destination": "geopolitical",
  "rubric_version": "finland-nato-usefulness-v1",
  "evidence_cutoff": "2023-04-30",
  "notes": "Two-part question by design (brainstorm Q15): a strategic cause plus a cutoff-specific accession-timing component, so use of the frozen corpus is observable rather than answerable from model memory."
}
```

Each `corpus/NN_slug.json`:

```json
{
  "excerpt_id": "01_reuters_finland_applies",
  "title": "<article headline as published>",
  "url": "https://www.reuters.com/...",
  "domain": "reuters.com",
  "publisher": "Reuters",
  "published_at": "2022-05-15",
  "retrieved_at": "2026-09-01",
  "truncation_note": "First N paragraphs; the remainder of the article is not reproduced.",
  "text": "<bounded excerpt, transcribed verbatim>"
}
```

**Review checklist that must be signed off in `docs/evals/2026Sep01_task-spec_finland-nato.md`
before Commit 4 starts** (this is the artifact the maintainer reviews):

1. Every excerpt is on an allow-listed domain and is real, transcribed, and bounded.
2. The corpus supports *both* halves of the question, and supports more than one
   legitimate emphasis (truth model: evidence map, not a golden answer).
3. The corpus is genuinely over-full — information overload is the chosen difficulty.
4. Supported claims, prohibited claims, and legitimate disagreements are enumerated
   in the spec (they are review material and judge context, not code).
5. The controlled-adapter mapping is stated: which excerpts become `Candidate`s,
   in what order, and what the agent's own `RETRIEVAL.fetch_candidates = 10` /
   `keep_sources = 8` truncation will do to them.
6. Expected execution evidence is stated: `destination == "geopolitical"`,
   a non-empty rewrite, ≥1 source, a non-empty answer.
7. The verifier contract is stated: the four usefulness criteria, the overall
   verdict, `faithful_to_combined_context`, and `expected_route`.
8. The report's claim boundary is stated verbatim: this validates the evaluation
   system, not GeopoliticAI's general geopolitical quality.

**Gate:** `cd app && uv run pytest tests/unit_tests/evals -q` — the real case must
load and hash-verify. Add one test that loads `finland_nato` from the real
`CASES_ROOT` and asserts the digest matches the lock file and that every excerpt
domain is in `agents.expert.consts.sources.ALLOWED_DOMAINS`.

**Then stop.** Commit 4 does not begin until the checklist is signed off.

---

### Commit 4 — The usefulness judge

**Files:** `app/evals/prompts.py`, `app/evals/judge.py`,
`app/tests/unit_tests/evals/test_judge.py`

**Why safe here:** a pure `LLMEvaluator` subclass. Tests drive it with a stub LLM;
no network, no Phoenix, no OpenAI key.

`app/evals/judge.py`:

```python
"""The pinned usefulness judge: one structured call, several Phoenix Scores.

Two constraints shape this module.

First, the settled design wants criterion-level scores *and* an independently
judged overall verdict from **one** structured call. Phoenix's own
`ClassificationEvaluator` returns exactly one `Score`, so this subclasses
`LLMEvaluator` and calls `llm.generate_object` with a schema covering every
criterion at once.

Second, the judge is pinned while the answer model is not: the answer follows
production's moving `gpt-4o-mini` alias, the judge is
`gpt-4o-mini-2024-07-18`. Same family, different resolution — recorded on every
Score so a report can never imply they are the same version.

The overall verdict is the model's, not a formula over the criteria. It may
contradict a failed criterion; that tradeoff is the point, and both the
breakdown and the explanations are retained so the contradiction is visible
(brainstorm: "Usefulness diagnostic output and aggregation").
"""

from __future__ import annotations

from typing import Any, ClassVar

from phoenix.evals import LLM, Score
from phoenix.evals.evaluators import EvalInput, LLMEvaluator

from evals.prompts import USEFULNESS_PROMPT_TEMPLATE

JUDGE_MODEL = "gpt-4o-mini-2024-07-18"
JUDGE_PROVIDER = "openai"
RUBRIC_VERSION = "finland-nato-usefulness-v1"

MEETS = "meets_usefulness_rubric"
DOES_NOT_MEET = "does_not_meet_usefulness_rubric"
CRITERIA: tuple[str, ...] = (
    "answers_both_parts",
    "general_reader_clarity",
    "prioritization",
    "concision",
)
_CRITERION_LABELS = {"meets": 1.0, "does_not_meet": 0.0}


def build_judge_llm() -> LLM:
    """Return the pinned judge client. `OPENAI_API_KEY` comes from the process env."""
    return LLM(provider=JUDGE_PROVIDER, model=JUDGE_MODEL)


class UsefulnessEvaluator(LLMEvaluator):
    """Score one answer against the usefulness rubric in a single call."""

    NAME: ClassVar[str] = "usefulness"

    def __init__(self, llm: LLM, **kwargs: Any) -> None:
        super().__init__(
            name=self.NAME,
            llm=llm,
            prompt_template=USEFULNESS_PROMPT_TEMPLATE,
            direction="maximize",
            **kwargs,
        )

    @staticmethod
    def response_schema() -> dict[str, Any]:
        """Return the JSON schema for the single structured judge response."""
        criterion = {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": list(_CRITERION_LABELS)},
                "explanation": {"type": "string"},
            },
            "required": ["label", "explanation"],
        }
        return {
            "type": "object",
            "properties": {
                **{name: dict(criterion) for name in CRITERIA},
                "overall": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "enum": [MEETS, DOES_NOT_MEET]},
                        "explanation": {"type": "string"},
                    },
                    "required": ["label", "explanation"],
                },
            },
            "required": [*CRITERIA, "overall"],
        }

    def _metadata(self) -> dict[str, Any]:
        """Return the provenance every Score from this judge carries."""
        return {
            "judge_model": JUDGE_MODEL,
            "judge_provider": JUDGE_PROVIDER,
            "rubric_version": RUBRIC_VERSION,
        }

    def _to_scores(self, response: dict[str, Any]) -> list[Score]:
        """Convert one structured response into criterion Scores plus the verdict."""
        scores: list[Score] = []
        for name in CRITERIA:
            block = response[name]
            label = str(block["label"])
            if label not in _CRITERION_LABELS:
                raise ValueError(f"Judge returned an unknown label for {name!r}: {label!r}")
            scores.append(
                Score(
                    name=f"usefulness.{name}",
                    label=label,
                    score=_CRITERION_LABELS[label],
                    explanation=str(block["explanation"]),
                    metadata=self._metadata(),
                    kind="llm",
                    direction="maximize",
                )
            )
        overall = response["overall"]
        overall_label = str(overall["label"])
        if overall_label not in (MEETS, DOES_NOT_MEET):
            raise ValueError(f"Judge returned an unknown overall label: {overall_label!r}")
        scores.append(
            Score(
                name="usefulness",
                label=overall_label,
                score=1.0 if overall_label == MEETS else 0.0,
                explanation=str(overall["explanation"]),
                metadata=self._metadata(),
                kind="llm",
                direction="maximize",
            )
        )
        return scores

    def _evaluate(self, eval_input: EvalInput) -> list[Score]:
        rendered = self.prompt_template.render(variables=eval_input)
        response = self.llm.generate_object(
            rendered, self.response_schema(), **self.invocation_parameters
        )
        return self._to_scores(response)
```

`app/evals/prompts.py` holds `USEFULNESS_PROMPT_TEMPLATE` — one mustache template
with `{{question}}`, `{{context}}`, `{{answer}}` — following the repo's
one-constant-per-purpose prompt convention. It states the reader (generally
informed), the format (concise briefing), the four criteria, and that the overall
verdict is the judge's own weighing rather than an all-or-nothing conjunction.

Tests (stub LLM, no network):

```python
class _StubLLM:
    model = "gpt-4o-mini-2024-07-18"

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple] = []

    def generate_object(self, prompt, schema, **kwargs):
        self.calls.append((prompt, schema))
        return self.response
```

asserting: exactly five Scores, named `usefulness.<criterion>` ×4 plus
`usefulness`; every Score carries `judge_model`/`rubric_version` metadata;
`meets_usefulness_rubric` → 1.0 and the other label → 0.0; an unknown criterion
label raises `ValueError`; the overall verdict is taken from the response and is
*not* recomputed from the criteria (assert a response where three criteria fail
but `overall == meets_usefulness_rubric` still yields `usefulness.score == 1.0`);
the rendered prompt contains the question, the answer, and one URL from the
context; the judge makes exactly one `generate_object` call per answer.

**Gate:** `cd app && uv run pytest tests/unit_tests/evals -q`

---

### Commit 5 — Grounding and route evaluators, and the zero-score rule

**Files:** `app/evals/grounding.py`, `app/evals/verdicts.py`,
`app/tests/unit_tests/evals/test_verdicts.py`

**Why safe here:** still pure. `verdicts.py` is where "wrong routing and genuine
agent failures score zero" is implemented once, so both scoring paths agree.

`app/evals/grounding.py` binds Phoenix's prebuilt evaluator and names the score
after what it actually measures:

```python
"""The grounding gate: Phoenix's prebuilt FaithfulnessEvaluator, and only that.

The reported score is `faithful_to_combined_context`, never `citation_valid`.
Faithfulness asks whether the answer is supported by, and does not contradict,
the supplied context. It cannot tell whether a citation is present, whether a
URL was copied exactly, or whether a cited URL came from the corpus at all — an
answer with supported prose and an invented link passes. Citation compliance is
deliberately outside the first Task (brainstorm: "First grounding gate").
"""

from __future__ import annotations

from phoenix.evals import LLM
from phoenix.evals.metrics import FaithfulnessEvaluator

GROUNDING_SCORE_NAME = "faithful_to_combined_context"


def build_grounding_evaluator(llm: LLM) -> FaithfulnessEvaluator:
    """Return the prebuilt faithfulness evaluator, unmodified."""
    return FaithfulnessEvaluator(llm=llm)
```

`app/evals/verdicts.py`:

```python
"""One place that decides when an observation scores zero without being asked.

Two product failures never reach a judge: the agent raised a `PipelineError`,
or the turn was routed away from the expert. Both are real user-visible
failures, so both score zero and the run stays valid. What must not happen is
each evaluator inventing its own rule, or an infrastructure failure being
laundered into a zero.
"""

from __future__ import annotations

from typing import Any

from evals.judge import CRITERIA, DOES_NOT_MEET, JUDGE_MODEL, RUBRIC_VERSION
from evals.grounding import GROUNDING_SCORE_NAME
from phoenix.evals import Score

OK = "ok"
AGENT_FAILURE = "agent_failure"


def product_failure_reason(output: dict[str, Any], expected_destination: str) -> str | None:
    """Return why this task output scores zero, or None if it should be judged."""
    if output.get("execution_status") != OK:
        return f"agent failure: {output.get('error_type')}: {output.get('error_message')}"
    if output.get("destination") != expected_destination:
        return (
            f"wrong route: expected {expected_destination!r}, "
            f"got {output.get('destination')!r}"
        )
    if not str(output.get("answer") or "").strip():
        return "agent produced an empty answer"
    return None


def _zero(name: str, label: str, reason: str) -> Score:
    return Score(
        name=name,
        label=label,
        score=0.0,
        explanation=reason,
        metadata={"scored_without_judge": True, "judge_model": JUDGE_MODEL,
                  "rubric_version": RUBRIC_VERSION},
        kind="code",
        direction="maximize",
    )


def zero_usefulness_scores(reason: str) -> list[Score]:
    """Return the full usefulness score set, all zero, with the cause recorded."""
    return [
        *(_zero(f"usefulness.{name}", "does_not_meet", reason) for name in CRITERIA),
        _zero("usefulness", DOES_NOT_MEET, reason),
    ]


def zero_grounding_score(reason: str) -> Score:
    """Return a zero grounding score for a run with no answer to ground."""
    return _zero(GROUNDING_SCORE_NAME, "unfaithful", reason)
```

Tests assert: an `ok` output on the expected route with a non-empty answer returns
`None`; a `agent_failure` status, a `"other"` destination, and a whitespace-only
answer each return a reason naming the cause; `zero_usefulness_scores` returns five
Scores all at 0.0 with `kind="code"` and `scored_without_judge`; the zero grounding
score is named `faithful_to_combined_context`.

**Gate:** `cd app && uv run pytest tests/unit_tests/evals -q`

---

### Commit 6 — Controlled adapters, the subprocess runner, and baseline isolation

**Files:** `app/evals/adapters.py`, `app/evals/runner.py`, `app/evals/revisions.py`,
`app/tests/unit_tests/evals/test_adapters.py`,
`app/tests/unit_tests/evals/test_runner_contract.py`

**Why safe here (and why it is last among the risky pieces):** it depends on the
corpus (Commit 2) and the frozen case (Commit 3) and is depended on by the Phoenix
task (Commit 7). It touches no application file. The interposition point already
exists: `app/src/agents/expert/nodes/search_and_fetch.py:12` does
`from search import fetch_sources, search_allowlisted`, binding both names as module
globals that the node body resolves at call time — the same seam
`tests/integration_tests/test_orchestrator_graph.py` already uses.

`app/evals/adapters.py`:

```python
"""Frozen stand-ins for Brave and trafilatura.

Patched into `agents.expert.nodes.search_and_fetch`, not into `search`: the node
binds `search_allowlisted` and `fetch_sources` as module globals at import, so
that module is the seam the running graph actually reads. This is the same seam
the existing integration tests use.

The adapters do not bypass the agent's own policy. Candidates are built from the
corpus and handed back in corpus order; the node then applies its real
`RETRIEVAL.fetch_candidates` and `keep_sources` truncation. The agent still
decides how many sources it carries — the corpus only decides what exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from evals.corpus import Case
from models import Candidate, Source


class FrozenSearch:
    """Deterministic search/fetch backed by one case's frozen corpus."""

    def __init__(self, case: Case) -> None:
        self.case = case
        self.queries: list[str] = []

    async def search_allowlisted(self, query: str, policy: Any) -> list[Candidate]:
        """Return every frozen excerpt as an allow-listed candidate, in corpus order."""
        self.queries.append(query)
        return [
            Candidate(title=excerpt.title, url=excerpt.url, domain=excerpt.domain)
            for excerpt in self.case.excerpts
        ]

    async def fetch_sources(
        self, candidates: Sequence[Candidate], policy: Any
    ) -> list[Source]:
        """Return the frozen text for each candidate the agent kept."""
        by_url = {excerpt.url: excerpt for excerpt in self.case.excerpts}
        return [by_url[candidate.url].as_source() for candidate in candidates]


def install(case: Case) -> FrozenSearch:
    """Patch the expert's retrieval seam for this process. Never reversed."""
    import agents.expert.nodes.search_and_fetch as node

    frozen = FrozenSearch(case)
    node.search_allowlisted = frozen.search_allowlisted  # type: ignore[assignment]
    node.fetch_sources = frozen.fetch_sources  # type: ignore[assignment]
    return frozen
```

`app/evals/runner.py` — the subprocess entrypoint. It is executed as
`python -m evals.runner` with `sys.path[0]` pointed at the revision under test:

```python
"""Run one orchestrator turn in an isolated process and print one JSON envelope.

Why a subprocess at all: the candidate and the baseline are two different
copies of the same module names. Importing both into one interpreter would
give whichever landed first, silently. Separate processes make the revision
under test a fact, not a hope (brainstorm: "Baseline process isolation").

Why it prints instead of returning: the parent runs under the candidate's
environment and must not import the baseline's modules at all. One JSON line on
stdout is the whole contract.

Exit status here is the *runner's* status, not the product's: a `PipelineError`
from the agent is a valid observation and exits 0 with
`execution_status="agent_failure"`. Only a broken harness exits nonzero.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any


def _load_source_root(source_root: Path) -> None:
    """Put the revision under test first on the import path, and prove it took."""
    sys.path.insert(0, str(source_root))
    import agents.orchestrator.graph as graph_module

    resolved = Path(graph_module.__file__ or "").resolve()
    if not resolved.is_relative_to(source_root.resolve()):
        # The venv installs the project via a .pth entry, so a sys.path insert
        # wins today. If that ever becomes a meta-path finder, the baseline
        # would silently run candidate code; refuse rather than mislabel.
        raise RuntimeError(
            f"Import path leaked: expected {source_root}, imported {resolved}"
        )


async def _run(case_id: str, cases_root: Path) -> dict[str, Any]:
    from evals.adapters import install
    from evals.corpus import load_case
    from agents.expert.config import ANSWER_LLM_SETTINGS
    from agents.orchestrator import build_graph, build_initial_orchestrator_state
    from agents.orchestrator.config import CLASSIFY_LLM_SETTINGS
    from config import init_environment, require_env
    from models import PipelineError

    init_environment()
    require_env()
    case = load_case(case_id, root=cases_root)
    frozen = install(case)

    envelope: dict[str, Any] = {
        "case_id": case.case_id,
        "corpus_digest": case.corpus_digest,
        "question": case.question,
        "answer_model": {
            "model": ANSWER_LLM_SETTINGS.model,
            "temperature": ANSWER_LLM_SETTINGS.temperature,
            "max_output_tokens": ANSWER_LLM_SETTINGS.max_output_tokens,
            "timeout_seconds": ANSWER_LLM_SETTINGS.timeout_seconds,
        },
        "classify_model": {"model": CLASSIFY_LLM_SETTINGS.model},
        "execution_status": "ok",
        "destination": None,
        "standalone_query": None,
        "source_urls": [],
        "answer": "",
        "error_type": None,
        "error_message": None,
    }

    started = time.monotonic()
    try:
        # No checkpointer: one turn, no thread, nothing to resume. The API's
        # Postgres saver is an API-lifespan concern and is not part of what this
        # benchmark measures.
        final = await build_graph().ainvoke(build_initial_orchestrator_state(case.question))
    except PipelineError as exc:
        envelope["execution_status"] = "agent_failure"
        envelope["error_type"] = type(exc).__name__
        envelope["error_message"] = str(exc)
    else:
        envelope["destination"] = final.get("destination")
        envelope["standalone_query"] = final.get("standalone_query")
        messages = final.get("messages", [])
        envelope["answer"] = messages[-1].text() if messages else ""
    envelope["duration_seconds"] = round(time.monotonic() - started, 3)
    envelope["rewritten_queries"] = list(frozen.queries)
    envelope["source_urls"] = [excerpt.url for excerpt in case.excerpts]
    return envelope


def main() -> int:
    """Parse arguments, run one turn, and print the envelope as one JSON line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--cases-root", required=True, type=Path)
    args = parser.parse_args()
    _load_source_root(args.source_root)
    envelope = asyncio.run(_run(args.case_id, args.cases_root))
    print(json.dumps(envelope, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Two details that are load-bearing:

- `--cases-root` is always the **candidate's** `app/evals/cases`. Both revisions
  read the same frozen evidence; only the application source differs (brainstorm:
  "Initial source baseline" — shared fixtures and environment, historical source).
- The baseline runs from a `git worktree`, which contains no `.env` (it is
  untracked). `config.init_environment()` calls `load_dotenv` on a path that will
  not exist there, which is a silent no-op — so `revisions.py` must pass
  `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, `PHOENIX_COLLECTOR_ENDPOINT`, and
  `PHOENIX_PROJECT_NAME` explicitly into the child environment, and fail the run as
  invalid if any required one is missing before spawning.

`app/evals/revisions.py`:

```python
"""Materialize the source revision under test, and run the runner against it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evals.errors import InvalidRunError

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_SOURCE = REPO_ROOT / "app" / "src"
CASES_ROOT = Path(__file__).resolve().parent / "cases"
PASSTHROUGH_ENV = (
    "OPENAI_API_KEY",
    "BRAVE_SEARCH_KEY",
    "PHOENIX_COLLECTOR_ENDPOINT",
    "PHOENIX_PROJECT_NAME",
    "LOG_LEVEL",
)
RUNNER_TIMEOUT_SECONDS = 300.0


@contextmanager
def source_tree(revision: str | None) -> Iterator[Path]:
    """Yield the `app/src` of `revision`, or the candidate's own when None."""
    if revision is None:
        yield CANDIDATE_SOURCE
        return
    with tempfile.TemporaryDirectory(prefix="geopoliticai-baseline-") as tmp:
        worktree = Path(tmp) / "src"
        try:
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(worktree), revision],
                cwd=REPO_ROOT, check=True, capture_output=True, text=True,
            )
            yield worktree / "app" / "src"
        except subprocess.CalledProcessError as exc:
            raise InvalidRunError(f"Could not check out {revision}: {exc.stderr}") from exc
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=REPO_ROOT, check=False, capture_output=True,
            )


def run_turn(*, case_id: str, source_root: Path) -> dict[str, Any]:
    """Run one turn in a child process and return its parsed envelope."""
    missing = [key for key in ("OPENAI_API_KEY", "BRAVE_SEARCH_KEY") if not os.getenv(key)]
    if missing:
        raise InvalidRunError(f"Missing credentials for a real run: {', '.join(missing)}")
    env = {
        "PATH": os.environ.get("PATH", ""),
        # `evals` lives at app/, not on the installed path; the child needs it.
        "PYTHONPATH": str(REPO_ROOT / "app"),
        **{key: value for key in PASSTHROUGH_ENV if (value := os.getenv(key)) is not None},
    }
    completed = subprocess.run(
        [sys.executable, "-m", "evals.runner",
         "--case-id", case_id,
         "--source-root", str(source_root),
         "--cases-root", str(CASES_ROOT)],
        cwd=REPO_ROOT / "app", env=env, capture_output=True, text=True,
        timeout=RUNNER_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise InvalidRunError(
            f"Runner failed (exit {completed.returncode}): {completed.stderr.strip()[-2000:]}"
        )
    try:
        return dict(json.loads(completed.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError) as exc:
        raise InvalidRunError(f"Runner produced no usable envelope: {completed.stdout!r}") from exc
```

Tests (no network, no model): `test_adapters.py` builds a `Case` from the synthetic
fixture, installs the adapters, and drives the *real*
`agents.expert.nodes.search_and_fetch.search_and_fetch` node, asserting it returns
frozen sources, respects `RETRIEVAL.keep_sources`, and records the query the
classifier rewrote. `test_runner_contract.py` asserts the envelope key set and that
`revisions.run_turn` raises `InvalidRunError` when `OPENAI_API_KEY` is unset
(monkeypatched) and when a stubbed subprocess returns non-JSON — the subprocess
itself is stubbed, never spawned.

**Gate:** `cd app && uv run pytest tests/unit_tests/evals -q`

---

### Commit 7 — Phoenix dataset sync and the experiment task

**Files:** `app/evals/dataset.py`, `app/evals/experiment.py`,
`app/tests/unit_tests/evals/test_experiment_wiring.py`

`app/evals/dataset.py` pushes the Git definition into Phoenix one way. Phoenix's
`create_dataset` uploads with `action="update"`, so repeated pushes of the same
name version the dataset rather than duplicating it:

```python
"""Git is canonical; Phoenix is a mirror. Synchronization is one-way, always."""

from __future__ import annotations

from phoenix.client import Client
from phoenix.client.resources.datasets import Dataset

from evals.corpus import Case, combined_context

DATASET_NAME = "geopoliticai-offline-pilot"


def push_case(client: Client, case: Case) -> Dataset:
    """Upload one case as a single Phoenix dataset example, and return the dataset."""
    return client.datasets.create_dataset(
        name=DATASET_NAME,
        dataset_description=(
            "Git-owned frozen-evidence benchmark cases. Edit under app/evals/cases/ "
            "and re-push; never edit in Phoenix."
        ),
        examples=[
            {
                "input": {"question": case.question, "case_id": case.case_id},
                "output": {},
                "metadata": {
                    "context": combined_context(case),
                    "corpus_digest": case.corpus_digest,
                    "expected_destination": case.expected_destination,
                    "rubric_version": case.rubric_version,
                    "excerpt_ids": [item.excerpt_id for item in case.excerpts],
                },
            }
        ],
    )
```

Note the deliberate `"output": {}` — the truth model is an evidence map with
multiple valid framings, so there is no expected answer to compare against.

`app/evals/experiment.py` builds the task and the three experiment evaluators:

```python
"""Wire the frozen case, the isolated runner, and the evaluators into Phoenix."""

from __future__ import annotations

from typing import Any, Callable

from phoenix.client.experiments import create_evaluator
from phoenix.evals import Score, bind_evaluator

from evals.corpus import Case
from evals.grounding import GROUNDING_SCORE_NAME, build_grounding_evaluator
from evals.judge import UsefulnessEvaluator, build_judge_llm
from evals.revisions import run_turn
from evals.verdicts import product_failure_reason, zero_grounding_score, zero_usefulness_scores


def build_task(case: Case, source_root: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return the sync Phoenix task that runs one orchestrator turn per example.

    Sync on purpose: `Client.experiments.run_experiment` raises
    "Task is async and cannot be run within sync implementation" for a
    coroutine task, and the turn happens in a child process anyway.
    """

    def task(input: dict[str, Any]) -> dict[str, Any]:
        return run_turn(case_id=str(input["case_id"]), source_root=source_root)

    task.__name__ = "orchestrator_turn"
    return task


def build_evaluators(case: Case) -> list[Any]:
    """Return the three experiment evaluators, in report order."""
    llm = build_judge_llm()
    judge = UsefulnessEvaluator(llm=llm)
    grounder = bind_evaluator(
        build_grounding_evaluator(llm),
        input_mapping={
            "input": "input.question",
            "output": "output.answer",
            "context": "metadata.context",
        },
    )

    @create_evaluator(kind="LLM", name="usefulness")
    def usefulness(input: dict[str, Any], output: dict[str, Any],
                   metadata: dict[str, Any]) -> list[Score]:
        # A plain function, not the evaluator object: Phoenix's own
        # `wrap_phoenix_evals_evaluator` keeps only `scores[0]`, which would
        # discard every criterion score. Returning the list keeps all five.
        reason = product_failure_reason(output, str(metadata["expected_destination"]))
        if reason is not None:
            return zero_usefulness_scores(reason)
        return judge.evaluate(
            {
                "question": input["question"],
                "context": metadata["context"],
                "answer": output["answer"],
            }
        )

    @create_evaluator(kind="LLM", name=GROUNDING_SCORE_NAME)
    def grounding(input: dict[str, Any], output: dict[str, Any],
                  metadata: dict[str, Any]) -> list[Score]:
        reason = product_failure_reason(output, str(metadata["expected_destination"]))
        if reason is not None:
            return [zero_grounding_score(reason)]
        scores = grounder.evaluate(
            {"input": input, "output": output, "metadata": metadata}
        )
        return [
            Score(
                name=GROUNDING_SCORE_NAME,
                label=score.label,
                score=score.score,
                explanation=score.explanation,
                metadata={**score.metadata, "judge_model": judge.llm.model},
                kind="llm",
                direction="maximize",
            )
            for score in scores
        ]

    @create_evaluator(kind="CODE", name="expected_route")
    def expected_route(output: dict[str, Any], metadata: dict[str, Any]) -> Score:
        expected = str(metadata["expected_destination"])
        actual = output.get("destination")
        matched = actual == expected
        return Score(
            name="expected_route",
            label="routed_as_expected" if matched else "routed_elsewhere",
            score=1.0 if matched else 0.0,
            explanation=f"expected {expected!r}, got {actual!r}",
            kind="code",
            direction="maximize",
        )

    return [usefulness, grounding, expected_route]
```

Tests: `test_experiment_wiring.py` monkeypatches `evals.revisions.run_turn` and
`evals.judge.build_judge_llm`, then calls the decorated evaluators directly — they
remain callable — asserting that an `agent_failure` output yields five zero
usefulness Scores and one zero grounding Score *without* invoking the judge, that a
`destination == "other"` output does the same, and that `expected_route` scores 1.0
only on the expected destination. `build_task` is asserted to be a plain function
(`not inspect.iscoroutinefunction`).

**Gate:** `cd app && uv run pytest tests/unit_tests/evals -q`

---

### Commit 8 — The CLI, the report artifact, exit semantics, and the pilot ledger

**Files:** `app/evals/report.py`, `app/evals/ledger.py`, `app/evals/cli.py`,
`app/tests/unit_tests/evals/test_report.py`,
`app/tests/unit_tests/evals/test_ledger.py`, `docs/evals/pilot-ledger.jsonl`

`app/evals/cli.py` exposes `run`:

```bash
cd app && uv run python -m evals.cli run \
    --case-id finland_nato \
    --baseline f179453 \
    --out ../docs/evals/runs/2026Sep01T1200_finland_nato.json
```

Non-interactive, environment-driven, machine-readable. Credentials and
`PHOENIX_COLLECTOR_ENDPOINT` come from the environment; nothing is prompted; the
JSON artifact is the contract a later GitHub Actions job would consume unchanged.

Exit semantics, implemented in `cli.py` and asserted in tests:

| Outcome | `validity` | Exit |
| --- | --- | --- |
| Both revisions ran, judged, any verdicts | `valid` | 0 |
| One or both revisions failed inside the agent (`PipelineError`, wrong route) and scored zero | `valid` | 0 |
| Missing `OPENAI_API_KEY`/`BRAVE_SEARCH_KEY`, Phoenix unreachable, dataset push failed | `invalid` | 2 |
| Corpus hash mismatch or missing case | `invalid` | 2 |
| Runner subprocess crashed or produced no envelope | `invalid` | 2 |
| Any Phoenix evaluation run came back with `error` set | `invalid` | 2 |

That last row is the reason `report.py` reads `RanExperiment["evaluation_runs"]`
and inspects `.error` on each: Phoenix records evaluator execution failures
separately from scores, and a judge that raised must invalidate the run rather
than silently reduce the score set.

`report.py` emits, per revision: the source revision, the shared environment
revision (`git rev-parse HEAD` of the working tree), the resolved answer-model
configuration from the envelope, the judge snapshot and rubric version, the
corpus digest, the execution evidence (route, rewrite, source URLs, answer
length, status), and every Score with its label, score, and explanation. Plus a
top-level block:

```json
{
  "claim_boundary": "Validates the evaluation system, not GeopoliticAI's general geopolitical quality. Usefulness labels are the pinned judge's rubric verdicts, self-calibrated for repeatability only — not validated against human preference. The grounding score is faithfulness to the combined frozen context, not citation validity.",
  "source_diff": "empty",
  "attribution_warning": "The answer model follows the moving `gpt-4o-mini` alias, so score differences cannot be attributed to repository changes alone."
}
```

`source_diff` is computed, not hardcoded: `git diff --quiet <baseline> HEAD -- app/src`.
When it is `empty`, the report says so, because a candidate/baseline delta then
measures generation and judge variance rather than code.

`ledger.py` appends one JSONL row per *valid* run to `docs/evals/pilot-ledger.jsonl`
(timestamp, candidate revision, baseline revision, corpus digest, both overall
labels, both grounding labels, validity) and the CLI prints pilot progress on every
run:

```
Pilot review trigger: 3/10 valid comparisons across 2/3 candidate revisions.
Owner: repository maintainer running the experiments.
On trigger: promote, revise, explicitly extend, or retire the pilot.
```

Invalid runs do not append and do not count, which is the settled rule.

Tests: `test_report.py` builds a synthetic `RanExperiment`-shaped dict and asserts
the JSON shape, that an `evaluation_runs` entry with `error` set flips validity to
`invalid`, that an `agent_failure` envelope stays `valid` with zero scores, and that
`claim_boundary` is present verbatim. `test_ledger.py` asserts append-only
behaviour in `tmp_path`, that invalid runs are not appended, and that progress
counts distinct candidate revisions rather than rows.

**Gate:** `cd app && uv run pytest tests/unit_tests -q` (the whole unit directory —
this is the commit where the harness becomes a program).

---

### Commit 9 — The judge-stability suite

**Files:** `app/evals/stability.py`,
`app/evals/fixtures/usefulness/{clear_pass,clear_fail,alternative_valid,borderline}.json`,
`app/tests/unit_tests/evals/test_stability.py`

Four fixed recorded answers × five judge repeats, reporting per-fixture agreement
and label flips, with no threshold and no gate:

```bash
cd app && uv run python -m evals.cli stability --out ../docs/evals/runs/2026Sep01_stability.json
```

This command needs `OPENAI_API_KEY` but **not** Phoenix: it is the separate
repeatability check, not an experiment. Its output must never be presented as
answer-model variance — it re-scores fixed text, so it measures only the judge.
`stability.py` states that in its module docstring and the artifact repeats it in a
`claim_boundary` field.

The four fixtures are recorded answers to the Finland question, authored during the
Commit 3 review alongside the corpus, and are the *only* recorded outputs this
design retains (brainstorm: "retain recorded outputs only for evaluator tests").

Tests drive `stability.py` with the stub LLM from Commit 4: agreement is 1.0 when
every repeat returns the same label; a 3/2 split reports 0.6 agreement and one
flip; a judge exception aborts with `InvalidRunError` rather than a partial report.

**Gate:** `cd app && uv run pytest tests/unit_tests -q`

---

### Commit 10 — Guidance and documentation sync

**Files:** `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
`app/README.md`, `docs/evals/README.md`

This repo's own rule (`CLAUDE.md`: "update `AGENTS.md`, `CLAUDE.md`, and
`.github/copilot-instructions.md` together" for any codebase change) makes this
commit mandatory, not optional. Each of the three gains the same facts, in each
file's own voice:

- `app/evals/` is the offline evaluation harness; it is never imported by
  application code and never reaches the runtime image (`Dockerfile` copies only
  `src/`); the import direction is `evals → src`, never the reverse.
- Git owns benchmark definitions under `app/evals/cases/<case_id>/`; every load
  hash-verifies against `corpus.lock.json`; Phoenix owns experiment runs only, and
  synchronization is one-way.
- Real experiments require a running Phoenix and `OPENAI_API_KEY`; evaluator
  component tests are standalone and use fixed data with no network.
- Two commands: `python -m evals.cli run` (Phoenix required) and
  `python -m evals.cli stability` (Phoenix not required).
- Exit semantics: valid runs exit 0 even when the verdicts are poor; invalid
  infrastructure, credential, evaluator, or execution conditions exit nonzero.
- The judge is pinned to `gpt-4o-mini-2024-07-18`; the answer model follows
  production's `gpt-4o-mini` alias; same family is not the same version.
- The pilot is non-blocking and observational, reviewed after ten valid comparisons
  across at least three candidate revisions, owned by the maintainer running them.
- Eval dependencies live in the `dev` dependency group; `pyproject.toml` now has
  `[tool.pytest.ini_options] pythonpath = ["."]`.
- The claim boundary: this validates the evaluation system, not general product
  quality.

`docs/evals/README.md` is the operator page: prerequisites (`docker compose up
phoenix`, the loopback port 6006 from `docker-compose.override.yml`, required env
vars), the two commands, how to read the artifact, and how to add a case — behind
the same review gate.

**Gate:**

```bash
cd app && uv run pytest tests/unit_tests -q && make lint
```

---

## 3. Test plan

### Tests that die

None. No existing test is deleted or rewritten.

### Tests that are rewritten

None.

### New tests (all standalone: fixed data, no network, no Phoenix, no OpenAI key)

| File | What it actually asserts |
| --- | --- |
| `test_errors.py` | `InvalidRunError` is not a `PipelineError` — the harness's failure class cannot be confused with the product's |
| `test_corpus.py` | A clean synthetic case loads; a mutated excerpt, a missing excerpt file, an unlocked excerpt, and a stale corpus digest each raise `InvalidRunError`; `combined_context` contains every excerpt URL once; the real `finland_nato` case verifies and every excerpt domain is in `ALLOWED_DOMAINS` |
| `test_judge.py` | One structured call produces exactly five Scores with the right names; label→score mapping; unknown labels raise; **the overall verdict is the judge's and is not recomputed from the criteria** (three failing criteria plus `meets_usefulness_rubric` still scores 1.0); every Score carries judge model and rubric version; the rendered prompt carries question, answer, and context |
| `test_verdicts.py` | `ok` + expected route + non-empty answer → judge it; `agent_failure`, wrong route, and empty answer each → a reason naming the cause; zero score sets are complete, `kind="code"`, and flagged `scored_without_judge` |
| `test_adapters.py` | The frozen adapters drive the **real** `search_and_fetch` node: candidates come from the corpus in order, the node's own `RETRIEVAL` truncation still applies, the rewritten query reaching search is recorded |
| `test_runner_contract.py` | The envelope key set is exactly what the evaluators read; `run_turn` raises `InvalidRunError` on missing credentials, on a nonzero child exit, and on unparsable stdout (subprocess stubbed, never spawned); `source_tree(None)` yields the candidate `app/src` |
| `test_experiment_wiring.py` | An `agent_failure` or wrongly-routed output produces zero scores **without calling the judge** (asserted by a judge stub that raises if called); `expected_route` scores 1.0 only on a match; the task is a sync callable |
| `test_report.py` | Artifact shape; an `evaluation_runs` entry with `error` set makes the run `invalid` (exit 2); an agent failure stays `valid` (exit 0); `claim_boundary` and `attribution_warning` are present; `source_diff` reflects the computed diff |
| `test_ledger.py` | Append-only; invalid runs are never appended; progress counts distinct candidate revisions, not rows |
| `test_stability.py` | Agreement 1.0 on unanimous repeats; 0.6 and one flip on a 3/2 split; a judge exception raises `InvalidRunError` instead of reporting partial data |

### Tests explicitly *not* written

- No test asserts that the deterministic suite is healthy, that the hanging
  integration test is fixed, or that timings are bounded. Out of scope by decision.
- No test calls OpenAI, Brave, Postgres, or Phoenix. The two real commands are
  operator-invoked and are not part of `pytest`.

---

## 4. Migration and rollout notes

### Schema and data migrations

None. Postgres is untouched — the runner invokes `build_graph()` with no
checkpointer, so the evaluation never writes a thread.

### Dependency changes

`arize-phoenix-client>=3.3,<4.0` and `arize-phoenix-evals>=3.5.1,<4.0` in the `dev`
group; `uv.lock` regenerated. `arize-phoenix-evals` pulls `pandas`, `pystache`,
`jsonpath-ng`, and `tqdm` into the dev environment. None reach the runtime image
(`uv sync --frozen --no-dev`). Both are compatible with the pinned Phoenix server
Compose already runs (`arizephoenix/phoenix:version-20.4.0`, which itself requires
`arize-phoenix-client>=3.2.0` and `arize-phoenix-evals>=3.5.1`) and with the
installed `openai>=1.40,<2.0` and `openinference-instrumentation 0.1.59`. Both
require Python `>=3.10,<3.15`; CI runs 3.11, the local venv 3.12.

CI (`.github/workflows/unit-tests.yml`) is unchanged: `uv sync --locked --dev`
installs the new group and bare `uv run pytest` collects the new standalone tests.
**Verify the lockfile is committed** — CI's `--locked` fails on a stale lock.

### Config and environment changes

No new variables. The harness reuses `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`
(required by `config.require_env()` even though search is stubbed — the runner
calls it to keep the environment contract identical to production),
`PHOENIX_COLLECTOR_ENDPOINT`, and `PHOENIX_PROJECT_NAME`, all already in the single
repo-root `.env`. `DATABASE_URL` is not needed.

Local Phoenix must be up for `run`: `docker compose up -d phoenix` exposes
`127.0.0.1:6006` through `docker-compose.override.yml`. The Phoenix client reads
its base URL from the standard Phoenix environment variables; `docs/evals/README.md`
states which one to set for a local server on 6006.

### Documentation this repo's own guidance requires updating

`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md` (all three, together —
Commit 10), plus `app/README.md` and the new `docs/evals/README.md`.
`docs/evals/2026Sep01_task-spec_finland-nato.md` is the reviewed Task Spec and
`docs/evals/pilot-ledger.jsonl` is the run ledger.

### Rollout

1. Commits 1–2 land; suite stays green.
2. Commit 3 lands; **stop for the maintainer's review of the Task Spec and corpus.**
3. Commits 4–10 land.
4. First real run: `python -m evals.cli run --case-id finland_nato --baseline f179453`.
   Expect the report to say `source_diff: empty` — run 1 measures the machinery
   and the noise floor, not a code change.
5. Ledger accumulates. At ten valid comparisons across three candidate revisions,
   the maintainer promotes, revises, explicitly extends, or retires the pilot.

---

## 5. Open questions and rejected objections

*(Filled in after the three reviews. Every finding is recorded here with its
disposition, whether accepted or rejected, and why.)*
