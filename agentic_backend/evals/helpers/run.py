"""Run one eval on Phoenix, then fail the process on any problem.

An eval's name says its kind. `<agent>_fixed` replays the inputs its dataset
holds: a case's recorded pages stand in for search. `<agent>_live` runs the
agent on today's web, and a run that fails becomes the case's report row. The
dataset is `datasets/<name>.json`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from collections.abc import Callable, Coroutine, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from config import init_environment, require_env
from evals.helpers import phoenix
from evals.helpers.graph import load_sources, replay_sources
from evals.helpers.judge import (
    JUDGE_ERROR,
    MIN_AVERAGE,
    NOT_APPLICABLE,
    Judge,
    Results,
    build_classifiers,
)
from evals.helpers.live import build_failure_row, print_row
from tracing import init_tracing

EvalKind = Literal["fixed", "live"]
# A coroutine function: Phoenix's experiment runner awaits each call itself.
Task = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
DATASETS_DIR = Path(__file__).parents[1] / "datasets"
TIMEOUT_SECONDS = 180
# A fixed eval replays its pages, so it needs no Brave key; a live eval searches.
FIXED_ENV_VARS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY")
LIVE_ENV_VARS = (*FIXED_ENV_VARS, "BRAVE_SEARCH_KEY")
# One name per idea across every dataset (brainstorm 2026Oct21 Q1).
InputKey = Literal["query", "messages", "sources", "replies"]
logger = logging.getLogger("agent")


class DatasetCase(BaseModel):
    """One case: a unique `name`, a `description`, an `input`, and, in a fixed eval only, `expected`.

    The kind rules read the eval's kind from the validation context. Keys a
    case carries beyond these four are ignored.
    """

    model_config = ConfigDict(strict=True)

    name: str
    description: str
    input: Annotated[dict[InputKey, Any], Field(min_length=1)]
    expected: dict[str, Any] | None = None

    @field_validator("description")
    @classmethod
    def _require_text(cls, description: str) -> str:
        if not description.strip():
            raise ValueError("a case needs a description")
        return description

    @model_validator(mode="after")
    def _follow_the_kind(self, info: ValidationInfo) -> DatasetCase:
        # Only `read_dataset` validates a case, and it always passes the kind.
        kind: EvalKind = (info.context or {})["kind"]
        if kind == "fixed" and not self.expected:
            raise ValueError(
                f"fixed case {self.name!r} needs a non-empty expected object"
            )
        if kind == "live" and "expected" in self.model_fields_set:
            raise ValueError(f"live case {self.name!r} must not have expected")
        # The live wrapper names each case's report row by its query.
        if kind == "live" and not isinstance(self.input.get("query"), str):
            raise ValueError(f"live case {self.name!r} needs a string query")
        return self


class Dataset(BaseModel):
    """A dataset file: `{"description": str, "cases": [...]}`, case names unique."""

    model_config = ConfigDict(strict=True)

    description: str
    cases: Annotated[list[DatasetCase], Field(min_length=1)]

    @field_validator("description")
    @classmethod
    def _require_text(cls, description: str) -> str:
        if not description.strip():
            raise ValueError("the dataset needs a description")
        return description

    @model_validator(mode="after")
    def _refuse_duplicate_names(self) -> Dataset:
        names = [case.name for case in self.cases]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate case names {duplicates}")
        return self


def eval_kind(eval_name: str) -> EvalKind:
    """Return the kind an eval's name ends in; any other name is refused."""
    if eval_name.endswith("_fixed"):
        return "fixed"
    if eval_name.endswith("_live"):
        return "live"
    raise ValueError(f"{eval_name}: an eval's name ends in _fixed or _live")


def read_dataset(path: Path) -> Dataset:
    """Validate a dataset file against `Dataset` for its eval's kind.

    A fixed case's `expected` holds the keys its judges check; a live case has
    none, and its judges read the run's own output. An invalid file raises a
    ValueError that names it.
    """
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    try:
        return Dataset.model_validate(raw, context={"kind": eval_kind(path.stem)})
    except ValidationError as error:
        raise ValueError(f"{path.name}: {error}") from error


def load_examples(path: Path) -> list[dict[str, Any]]:
    """Return a valid dataset's cases as Phoenix's `{input, output, metadata}` examples."""
    return [
        {
            "input": case.input,
            "output": case.expected or {},
            "metadata": {"name": case.name, "description": case.description},
        }
        for case in read_dataset(path).cases
    ]


def dataset_name(eval_name: str, path: Path) -> str:
    """Name the platform dataset after the file's content, so an edit makes a new one."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    return f"geopoliticai-{eval_name}-{digest}"


def experiment_name(eval_name: str) -> str:
    """Name the experiment after the commit and time it ran at."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "nogit"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{eval_name}-{commit}-{timestamp}"


def failures(
    results: Results, judges: Sequence[Judge], example_count: int
) -> list[str]:
    """List every reason this run must fail; empty means it passed."""
    problems = [f"task failed: {error}" for error in results.task_errors]
    for judge in judges:
        verdicts = results.verdicts.get(judge.name, [])
        if len(verdicts) != example_count:
            problems.append(
                f"{judge.name}: {len(verdicts)} results for {example_count} examples"
            )
            continue
        errors = [verdict for verdict in verdicts if verdict.label == JUDGE_ERROR]
        if errors:
            problems.append(
                f"{judge.name}: {len(errors)} judge error(s); first: {errors[0].explanation}"
            )
            continue
        scores = [
            verdict.score
            for verdict in verdicts
            if verdict.label != NOT_APPLICABLE and verdict.score is not None
        ]
        if not scores:
            logger.info("%s: not applicable to any example", judge.name)
            continue
        average = sum(scores) / len(scores)
        minimum = MIN_AVERAGE[judge.kind]
        logger.info(
            "%s: average %.2f over %d example(s), minimum %.2f",
            judge.name,
            average,
            len(scores),
            minimum,
        )
        if average < minimum:
            problems.append(
                f"{judge.name}: average {average:.2f} is below {minimum:.2f}"
            )
    return problems


async def run(
    *,
    eval_name: str,
    task: Task,
    judges: Sequence[Judge],
    timeout: int = TIMEOUT_SECONDS,
    extra_env_vars: Sequence[str] = (),
) -> None:
    """Run `task` over the eval's dataset, judge it, upload everything, then gate.

    `extra_env_vars` are keys this eval's agent needs beyond its kind's, checked
    here, before any case: inside a live task a missing key would turn into one
    "ours" row per case instead of one clear error.
    """
    kind = eval_kind(eval_name)
    dataset_path = DATASETS_DIR / f"{eval_name}.json"
    examples = load_examples(dataset_path)
    init_environment()
    require_env(
        (*(LIVE_ENV_VARS if kind == "live" else FIXED_ENV_VARS), *extra_env_vars)
    )
    if not init_tracing():
        raise RuntimeError("Phoenix tracing could not be initialized")
    results = await phoenix.run(
        dataset_name=dataset_name(eval_name, dataset_path),
        experiment_name=experiment_name(eval_name),
        examples=examples,
        task=_wrap_live_task(task) if kind == "live" else _wrap_fixed_task(task),
        judges=judges,
        classifiers=build_classifiers(judges),
        timeout=timeout,
    )
    for name, verdicts in results.verdicts.items():
        for verdict in verdicts:
            logger.info("%s %s: %s", name, verdict.label, verdict.explanation)
    problems = failures(results, judges, len(examples))
    for problem in problems:
        logger.error("%s eval: %s", eval_name, problem)
    if problems:
        raise SystemExit(1)
    logger.info("%s eval passed", eval_name)


def _wrap_fixed_task(task: Task) -> Task:
    """Run each case with its recorded pages in place of search; no pages, no search."""

    async def run_case(input: dict[str, Any]) -> dict[str, Any]:
        sources = load_sources(input["sources"]) if "sources" in input else None
        with replay_sources(sources):
            return await task(input)

    return run_case


def _wrap_live_task(task: Task) -> Task:
    """Run each case live; a failure becomes the case's report row, never a crash."""

    async def run_case(input: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            output = await task(input)
        except Exception as error:  # noqa: BLE001 - a failed live run is a report row (Q8)
            # The traceback, logged: a KeyError of ours must not hide behind
            # the one-line cause the row shows (review thread).
            logger.exception("the live run failed: %s", input["query"])
            output = build_failure_row(error, {})
        row = {"finished": True, "side": "", "cause": "", "step_seconds": {}, **output}
        print_row(input["query"], row, time.monotonic() - started)
        return row

    return run_case
