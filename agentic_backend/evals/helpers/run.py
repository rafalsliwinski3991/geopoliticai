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
from typing import Any, Literal

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
INPUT_KEYS = frozenset({"query", "messages", "sources", "replies"})
logger = logging.getLogger("agent")


def eval_kind(eval_name: str) -> EvalKind:
    """Return the kind an eval's name ends in; any other name is refused."""
    if eval_name.endswith("_fixed"):
        return "fixed"
    if eval_name.endswith("_live"):
        return "live"
    raise ValueError(f"{eval_name}: an eval's name ends in _fixed or _live")


def load_examples(path: Path) -> list[dict[str, Any]]:
    """Load a dataset and return Phoenix's `{input, output, metadata}` examples.

    The file is `{"description": str, "cases": [...]}`. A case has a unique
    `name`, a `description`, an `input` built from `INPUT_KEYS`, and, in a
    fixed eval only, `expected`: the keys its judges check. A live case has no
    `expected`; its judges read the run's own output.
    """
    kind = eval_kind(path.stem)
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f'{path.name} must be {{"description": str, "cases": [...]}}')
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{path.name}: the dataset needs a description")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path.name}: cases must be a non-empty list")
    names: set[str] = set()
    return [_read_case(path.name, kind, case, names) for case in cases]


def _read_case(
    file_name: str, kind: EvalKind, case: object, names: set[str]
) -> dict[str, Any]:
    """Check one case against the contract and return it as a Phoenix example."""
    if not (isinstance(case, dict) and isinstance(case.get("name"), str)):
        raise ValueError(f"{file_name}: every case needs a string name")
    name: str = case["name"]
    if name in names:
        raise ValueError(f"{file_name}: duplicate case name {name!r}")
    names.add(name)
    description = case.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{file_name}: case {name!r} needs a description")
    input = case.get("input")
    if not isinstance(input, dict) or not input:
        raise ValueError(f"{file_name}: case {name!r} needs a non-empty input object")
    unknown = sorted(set(input) - INPUT_KEYS)
    if unknown:
        raise ValueError(f"{file_name}: case {name!r} has unknown input keys {unknown}")
    expected = case.get("expected")
    if kind == "fixed" and not (isinstance(expected, dict) and expected):
        raise ValueError(
            f"{file_name}: fixed case {name!r} needs a non-empty expected object"
        )
    if kind == "live" and "expected" in case:
        raise ValueError(f"{file_name}: live case {name!r} must not have expected")
    return {
        "input": input,
        "output": expected or {},
        "metadata": {"name": name, "description": description},
    }


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
        with replay_sources(lambda: sources):
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
