"""Judge definitions and per-example scoring shared by both platforms."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

JudgeKind = Literal["binary", "numeric"]
# (input, output, expected) -> the variables a prompt or check reads, or None
# when the judge does not apply to this example.
View = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]], "dict[str, Any] | None"
]

BINARY_CHOICES: dict[str, float | int] = {"fail": 0.0, "pass": 1.0}
NUMERIC_CHOICES: dict[str, float | int] = {
    "1": 0.0,
    "2": 0.25,
    "3": 0.5,
    "4": 0.75,
    "5": 1.0,
}
# Numeric 0.75 is today's 4-of-5 bar; binary checks must pass on every example.
MIN_AVERAGE: dict[str, float] = {"binary": 1.0, "numeric": 0.75}
NOT_APPLICABLE = "not_applicable"
JUDGE_ERROR = "judge_error"
JUDGE_RETRIES = 3
# Pinned, not `openrouter/free`; see git history.
JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Markdown link targets only: the match stops at the first ')', so a URL that
# legitimately contains a parenthesis is truncated. Every dataset recorded so
# far uses https://news.example/... URLs without parentheses; write balanced
# parenthesis handling here before recording a source URL that has any.
MARKDOWN_LINK_URL = re.compile(r"\]\((https?://[^)\s]+)\)")
logger = logging.getLogger("agent")


@dataclass(frozen=True)
class Judge:
    """One named check: an LLM judge (`prompt`) or a code check (`check`).

    `view` decides applicability from the expected output only, so a missing
    actual output fails the judge instead of skipping it.
    """

    name: str
    kind: JudgeKind
    view: View
    prompt: str | None = None
    check: Callable[[dict[str, Any]], bool] | None = None

    def __post_init__(self) -> None:
        """Reject judges that are both or neither kind of evaluator."""
        if (self.prompt is None) == (self.check is None):
            raise ValueError(f"{self.name}: set exactly one of prompt or check")
        if self.check is not None and self.kind != "binary":
            raise ValueError(f"{self.name}: code checks must be binary")

    @property
    def choices(self) -> dict[str, float | int]:
        """Labels this judge may return, mapped to their 0-1 scores."""
        return BINARY_CHOICES if self.kind == "binary" else NUMERIC_CHOICES


@dataclass(frozen=True)
class Verdict:
    """One judge's result for one example."""

    label: str
    score: float | None = None
    explanation: str = ""


@dataclass(frozen=True)
class Results:
    """One experiment's outcome in platform-neutral form."""

    task_errors: list[str]
    verdicts: dict[str, list[Verdict]]


def markdown_link_urls(text: str) -> list[str]:
    """Return every URL written as a markdown link target."""
    return MARKDOWN_LINK_URL.findall(text)


def build_classifiers(judges: Sequence[Judge]) -> dict[str, Any]:
    """Build one Phoenix classification evaluator per LLM judge."""
    from phoenix.evals import LLM, ClassificationEvaluator

    llm = LLM(
        provider="openai",
        model=JUDGE_MODEL,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
    )
    return {
        judge.name: ClassificationEvaluator(
            name=judge.name,
            llm=llm,
            prompt_template=judge.prompt,
            choices=judge.choices,
            include_explanation=True,
            temperature=0,
        )
        for judge in judges
        if judge.prompt is not None
    }


def verdict_from_label(judge: Judge, label: object, explanation: object) -> Verdict:
    """Rebuild a verdict from what a platform stored; anything unknown is an error."""
    text = explanation if isinstance(explanation, str) else ""
    if label == NOT_APPLICABLE:
        return Verdict(NOT_APPLICABLE, explanation=text)
    if isinstance(label, str) and label in judge.choices:
        return Verdict(label, float(judge.choices[label]), text)
    return Verdict(
        JUDGE_ERROR,
        explanation=text or "The platform recorded no result for this judge.",
    )


def _prepare(
    judge: Judge,
    input: Mapping[str, Any],
    output: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> Verdict | dict[str, Any]:
    """Return a final verdict, or the variables an LLM judge still has to read."""
    if output is None:
        # The task crashed; its error already fails the run.
        return Verdict(NOT_APPLICABLE, explanation="The task produced no output.")
    try:
        variables = judge.view(dict(input), dict(output), dict(expected))
        if variables is None:
            return Verdict(NOT_APPLICABLE)
        if judge.check is not None:
            passed = judge.check(variables)
            return Verdict("pass" if passed else "fail", 1.0 if passed else 0.0)
    except Exception as exc:
        logger.error("%s errored: %s", judge.name, exc)
        return Verdict(JUDGE_ERROR, explanation=f"{type(exc).__name__}: {exc}")
    return variables


def _classified(judge: Judge, result: Any) -> Verdict | str:
    """Return the verdict for a valid label, or why the label was rejected."""
    if result.label in judge.choices:
        return Verdict(
            result.label, float(judge.choices[result.label]), result.explanation or ""
        )
    return f"label {result.label!r} is not one of {sorted(judge.choices)}"


def _gave_up(judge: Judge, last_error: str) -> Verdict:
    logger.error("%s judge error: %s", judge.name, last_error)
    return Verdict(
        JUDGE_ERROR,
        explanation=f"Judge failed after {JUDGE_RETRIES} attempts: {last_error}",
    )


def score(
    judge: Judge,
    classifier: Any,
    input: Mapping[str, Any],
    output: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> Verdict:
    """Score one example synchronously (AX). Never raises."""
    prepared = _prepare(judge, input, output, expected)
    if isinstance(prepared, Verdict):
        return prepared
    last_error = "no attempt was made"
    for _attempt in range(JUDGE_RETRIES):
        try:
            outcome = _classified(judge, classifier.evaluate(prepared)[0])
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            # The free judge model is rate limited: back off between attempts.
            time.sleep(2**_attempt)
            continue
        if isinstance(outcome, Verdict):
            return outcome
        last_error = outcome
    return _gave_up(judge, last_error)


async def async_score(
    judge: Judge,
    classifier: Any,
    input: Mapping[str, Any],
    output: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> Verdict:
    """Score one example on the event loop (Phoenix). Never raises.

    Async like today's runner: a sync judge call would block the loop, and
    `evaluate_experiment(timeout=...)` could not interrupt a hung request.
    """
    prepared = _prepare(judge, input, output, expected)
    if isinstance(prepared, Verdict):
        return prepared
    last_error = "no attempt was made"
    for _attempt in range(JUDGE_RETRIES):
        try:
            outcome = _classified(judge, (await classifier.async_evaluate(prepared))[0])
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            # The free judge model is rate limited: back off between attempts.
            await asyncio.sleep(2**_attempt)
            continue
        if isinstance(outcome, Verdict):
            return outcome
        last_error = outcome
    return _gave_up(judge, last_error)
