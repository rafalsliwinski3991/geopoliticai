"""Judge definitions and per-example scoring."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

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
JUDGE_BACKOFF_INITIAL_SECONDS = 1.0
JUDGE_BACKOFF_MAX_SECONDS = 8.0
JUDGE_BACKOFF_JITTER_SECONDS = 1.0
# phoenix-evals raises a bare ValueError for a bad answer (invalid label, no
# tool call, no content) and for deterministic misuse alike; only these
# messages are worth another attempt. OpenRouter answers a rate-limited or
# failed free-model call with HTTP 200 and `choices: null`, which surfaces as
# a TypeError from `response.choices[0]`.
PHOENIX_BAD_ANSWER_MARKERS = (
    "received invalid label",
    "No tool calls in response",
    "OpenAI returned None content",
    "'NoneType' object is not subscriptable",
)
# Paid, cheap, and not from OpenAI, whose models answer every eval (user
# decision 2026-10-20): the free `nvidia/nemotron-3-super-120b-a12b:free`
# endpoint answered 404 on every call that day. $0.10/$0.50 per million tokens
# in/out, checked 2026-10-20; the slug lists `tools` and `tool_choice`.
JUDGE_MODEL = "anthropic/claude-haiku-5.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Markdown link targets: one level of `(...)` inside the URL is part of it, so
# https://en.wikipedia.org/wiki/Foo_(bar) is captured whole. The handling is
# one level deep: an unmatched ')' still ends the URL, and a URL with nested or
# unbalanced '(' is not matched at all.
MARKDOWN_LINK_URL = re.compile(r"\]\((https?://[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)\)")
logger = logging.getLogger("agent")


@dataclass(frozen=True)
class Judge:
    """One named check: an LLM judge (`prompt`) or a code check (`check`).

    `view` decides applicability, normally from the expected output only, so
    a missing actual output fails the judge instead of skipping it. A live
    eval (`*_live`) has no expected output: its views decide from the actual
    output, and its `finished_or_outside` judge fails the run when the run
    failed for a reason of ours.
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


class _InvalidLabel(Exception):
    """The judge answered, but with a label outside its choices."""


def _is_phoenix_bad_answer(exc: BaseException) -> bool:
    return isinstance(exc, (ValueError, TypeError)) and any(
        marker in str(exc) for marker in PHOENIX_BAD_ANSWER_MARKERS
    )


def _retry_policy() -> dict[str, Any]:
    """The backoff policy `async_score` retries under."""
    import openai
    from phoenix.evals.rate_limiters import RateLimitError as PhoenixRateLimitError

    transient = (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.InternalServerError,
        PhoenixRateLimitError,
        _InvalidLabel,
    )
    return {
        "stop": stop_after_attempt(JUDGE_RETRIES),
        "wait": wait_exponential_jitter(
            initial=JUDGE_BACKOFF_INITIAL_SECONDS,
            max=JUDGE_BACKOFF_MAX_SECONDS,
            jitter=JUDGE_BACKOFF_JITTER_SECONDS,
        ),
        "retry": retry_if_exception_type(transient)
        | retry_if_exception(_is_phoenix_bad_answer),
        "reraise": True,
    }


def _verdict_or_raise(judge: Judge, result: Any) -> Verdict:
    outcome = _classified(judge, result)
    if isinstance(outcome, Verdict):
        return outcome
    raise _InvalidLabel(outcome)


def _gave_up(judge: Judge, attempts: int, last_error: str) -> Verdict:
    logger.error("%s judge error: %s", judge.name, last_error)
    return Verdict(
        JUDGE_ERROR,
        explanation=(
            f"Judge failed after {attempts} attempt{'s' if attempts != 1 else ''}: "
            f"{last_error}"
        ),
    )


async def async_score(
    judge: Judge,
    classifier: Any,
    input: Mapping[str, Any],
    output: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> Verdict:
    """Score one example on the event loop. Never raises.

    Async like today's runner: a sync judge call would block the loop, and
    `evaluate_experiment(timeout=...)` could not interrupt a hung request.
    """
    prepared = _prepare(judge, input, output, expected)
    if isinstance(prepared, Verdict):
        return prepared
    attempts = 0
    try:
        async for attempt in AsyncRetrying(**_retry_policy()):
            with attempt:
                attempts = attempt.retry_state.attempt_number
                return _verdict_or_raise(
                    judge, (await classifier.async_evaluate(prepared))[0]
                )
    except Exception as exc:  # noqa: BLE001 - scoring never raises
        return _gave_up(judge, attempts, f"{type(exc).__name__}: {exc}")
    raise AssertionError("unreachable: tenacity either returns or reraises")
