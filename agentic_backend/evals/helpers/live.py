"""How a live eval reports a run that failed: whose failure it was, and one printed row."""

from __future__ import annotations

from typing import Any

OUTSIDE = "outside"
OURS = "ours"


def classify_failure(error: BaseException) -> str:
    """Return whose failure a failed live run was: "outside" or "ours" (brainstorm 2026Oct19 Q2).

    Outside only for a provider outage: every Brave search failed
    (`SearchUnavailableError`), every council member without a ballot failed
    on the provider's side (`QuorumError.outside`), or a model call's cause
    chain holds a connection error, a 429 or a 5xx. A refused request (another
    4xx), our time limits and the wall, and every check of ours are ours.
    """
    import openai

    # The outage threshold and the label are the council's, imported, not copies that drift (review thread).
    from agents.deep_forecaster.council import SERVER_ERROR_STATUS, QuorumError
    from models import SearchUnavailableError

    if isinstance(error, SearchUnavailableError):
        return OUTSIDE
    if isinstance(error, QuorumError):
        return OUTSIDE if error.outside else OURS
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, (openai.APIConnectionError, openai.RateLimitError)):
            return OUTSIDE
        if (
            isinstance(cause, openai.APIStatusError)
            and cause.status_code >= SERVER_ERROR_STATUS
        ):
            return OUTSIDE
        cause = cause.__cause__
    return OURS


def build_failure_row(
    error: BaseException, step_seconds: dict[str, float]
) -> dict[str, Any]:
    """Return a failed run as a report row: whose failure, and what it said."""
    return {
        "finished": False,
        "side": classify_failure(error),
        "cause": f"{type(error).__name__}: {error}",
        "step_seconds": step_seconds,
    }


def print_row(query: str, output: dict[str, Any], total: float) -> None:
    """Print one report row: finished, side, voters, research and total seconds, cause."""
    print(
        f"{'finished' if output['finished'] else 'failed':8} "
        f"{output['side'] or '-':7} "
        f"voters {output.get('members_voting', '-')} "
        f"research {output['step_seconds'].get('research', '-')} s "
        f"total {total:.0f} s | {query} | {output['cause'] or '-'}"
    )
