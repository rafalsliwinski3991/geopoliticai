"""Unit tests for `evals.helpers.live`."""

from __future__ import annotations

from typing import Any

import httpx
import openai
import pytest

from agents.deep_forecaster.council import QuorumError
from evals.helpers.live import build_failure_row, classify_failure, print_row
from models import LLMInvocationError, ResearchLimitError, SearchUnavailableError

_ROUTER_REQUEST = httpx.Request("POST", "https://router.example/v1")


def _model_error(kind: type[openai.APIStatusError], status: int) -> BaseException:
    """Return a model-call failure whose cause chain carries `kind` with `status`."""
    response = httpx.Response(
        status, request=httpx.Request("POST", "https://router.example/v1")
    )
    call = kind("the model call failed", response=response, body=None)
    wrapped: BaseException = RuntimeError("the step failed")
    wrapped.__cause__ = call
    return wrapped


def _wrapped(error: BaseException, hops: int = 1) -> BaseException:
    """Return `error` wrapped in `hops` RuntimeErrors, the first as `__cause__`."""
    for _ in range(hops):
        wrapper: BaseException = RuntimeError("the step failed")
        wrapper.__cause__ = error
        error = wrapper
    return error


@pytest.mark.parametrize(
    ("error", "side"),
    [
        pytest.param(
            SearchUnavailableError("every search failed"),
            "outside",
            id="every search failed",
        ),
        pytest.param(
            QuorumError("round 1 ended below quorum", outside=True),
            "outside",
            id="council down in an outage",
        ),
        pytest.param(
            QuorumError("round 1 ended below quorum", outside=False),
            "ours",
            id="council broke our rules",
        ),
        pytest.param(
            _model_error(openai.APIStatusError, 503),
            "outside",
            id="5xx under a model call",
        ),
        pytest.param(
            _model_error(openai.APIStatusError, 500),
            "outside",
            id="exactly the 5xx boundary",
        ),
        pytest.param(
            _model_error(openai.APIStatusError, 499),
            "ours",
            id="one below the 5xx boundary",
        ),
        pytest.param(
            _model_error(openai.RateLimitError, 429),
            "outside",
            id="429 under a model call",
        ),
        pytest.param(
            _model_error(openai.AuthenticationError, 401),
            "ours",
            id="refused auth under a model call",
        ),
        pytest.param(
            _model_error(openai.APIStatusError, 400),
            "ours",
            id="refused request under a model call",
        ),
        pytest.param(
            _wrapped(openai.APIConnectionError(request=_ROUTER_REQUEST)),
            "outside",
            id="connection error under a model call",
        ),
        pytest.param(
            _wrapped(openai.APITimeoutError(_ROUTER_REQUEST)),
            "outside",
            id="timeout under a model call",
        ),
        pytest.param(
            _wrapped(
                openai.RateLimitError(
                    "rate limited",
                    response=httpx.Response(
                        429, request=httpx.Request("POST", "https://router.example/v1")
                    ),
                    body=None,
                ),
                hops=2,
            ),
            "outside",
            id="two hops to the outage",
        ),
        pytest.param(
            TimeoutError("claim drafting timed out"),
            "ours",
            id="our step timeout",
        ),
        pytest.param(
            LLMInvocationError("the verification found a defect"),
            "ours",
            id="our analysis check",
        ),
        pytest.param(
            ResearchLimitError("The forecast ran past its 840-second wall."),
            "ours",
            id="past the wall",
        ),
    ],
)
def test_classify_failure_calls_only_an_outage_outside(
    error: BaseException, side: str
) -> None:
    # Arrange: `error` comes from the parametrization above — each case is one
    # failure shape the run's boundary can meet.
    # Act
    verdict = classify_failure(error)
    # Assert
    assert verdict == side


def test_a_failure_row_names_the_side_and_the_cause() -> None:
    """The report row says whose failure it was and what the error said."""
    # Arrange
    error = SearchUnavailableError("every search failed")
    # Act
    row = build_failure_row(error, {"research": 4.0})
    # Assert
    assert row == {
        "finished": False,
        "side": "outside",
        "cause": "SearchUnavailableError: every search failed",
        "step_seconds": {"research": 4.0},
    }


def test_a_report_row_shows_finished_side_voters_research_total_and_cause(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One printed line per question keeps the run's report readable at a glance."""
    # Arrange
    output: dict[str, Any] = {
        "finished": False,
        "side": "outside",
        "cause": "SearchUnavailableError: x",
        "step_seconds": {"research": 4.0},
    }
    # Act
    print_row("Q", output, 9.0)
    # Assert
    assert (
        capsys.readouterr().out
        == "failed   outside voters - research 4.0 s total 9 s | Q | SearchUnavailableError: x\n"
    )


def test_a_finished_row_shows_dashes_for_the_side_and_cause_it_lacks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A finished run has no side, no cause, and maybe no research step; each prints as `-`."""
    # Arrange
    output: dict[str, Any] = {
        "finished": True,
        "side": "",
        "cause": "",
        "members_voting": 7,
        "step_seconds": {},
    }
    # Act
    print_row("Q", output, 12.4)
    # Assert
    assert (
        capsys.readouterr().out
        == "finished -       voters 7 research - s total 12 s | Q | -\n"
    )
