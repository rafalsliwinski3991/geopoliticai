"""Run one eval on the configured platform, then fail the process on any problem."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Callable, Coroutine, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_arize_platform, init_environment, require_env
from evals.helpers import ax, phoenix
from evals.helpers.judge import (
    JUDGE_ERROR,
    MIN_AVERAGE,
    NOT_APPLICABLE,
    Judge,
    Results,
    build_classifiers,
)
from tracing import init_tracing

# Coroutine, not Awaitable: the AX path hands the call to `asyncio.run`.
Task = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
TIMEOUT_SECONDS = 180
# Brave is deliberately absent: evals patch retrieval with recorded sources.
EVAL_ENV_VARS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY")
logger = logging.getLogger("agent")


def load_examples(path: Path) -> list[dict[str, Any]]:
    """Load a dataset and return the platform's `{input, output}` pairs.

    Two shapes are accepted (review thread, #149): the legacy `[{name, input,
    output}]` list and the documented wrapper `{"description": str, "cases":
    [...]}`, which carries the dataset's purpose for a new developer.
    """
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    description: object = None
    if isinstance(raw, dict):
        description = raw.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{path.name}: a wrapper dataset needs a description")
        raw = raw.get("cases")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"{path.name} must be a non-empty list of examples or "
            '{{"description": str, "cases": [...]}}'
        )
    names: set[str] = set()
    for example in raw:
        if not (
            isinstance(example, dict)
            and isinstance(example.get("name"), str)
            and isinstance(example.get("input"), dict)
            and isinstance(example.get("output"), dict)
        ):
            raise ValueError(
                f"{path.name}: every example needs a string name and object input and output"
            )
        if example["name"] in names:
            raise ValueError(f"{path.name}: duplicate example name {example['name']!r}")
        names.add(example["name"])
        if "description" in example and not isinstance(example["description"], str):
            raise ValueError(
                f"{path.name}: example {example['name']!r}'s description must be a string"
            )
    return [{"input": example["input"], "output": example["output"]} for example in raw]


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
    dataset_path: Path,
    task: Task,
    judges: Sequence[Judge],
    timeout: int = TIMEOUT_SECONDS,
) -> None:
    """Run `task` over the dataset, judge it, upload everything, then gate."""
    examples = load_examples(dataset_path)
    init_environment()
    require_env(EVAL_ENV_VARS)
    platform = get_arize_platform()
    if platform == "AX":
        require_env(("ARIZE_API_KEY", "ARIZE_SPACE_ID"))
    if not init_tracing():
        raise RuntimeError(f"{platform} tracing could not be initialized")
    arguments: dict[str, Any] = {
        "dataset_name": dataset_name(eval_name, dataset_path),
        "experiment_name": experiment_name(eval_name),
        "examples": examples,
        "task": task,
        "judges": judges,
        "classifiers": build_classifiers(judges),
        "timeout": timeout,
    }
    if platform == "AX":
        results = await ax.run(**arguments)
    else:
        results = await phoenix.run(**arguments)
    for name, verdicts in results.verdicts.items():
        for verdict in verdicts:
            logger.info("%s %s: %s", name, verdict.label, verdict.explanation)
    problems = failures(results, judges, len(examples))
    for problem in problems:
        logger.error("%s eval: %s", eval_name, problem)
    if problems:
        raise SystemExit(1)
    logger.info("%s eval passed", eval_name)
