"""e2e_deep_forecaster eval: the whole deep forecaster, live, on questions users asked.

Brainstorm 2026Oct19 (Q5-Q8): the only forecaster eval. Five questions from
the Phoenix traces, typed as users typed them, each run once with live Brave
searches, live page reading, Gemini's video reading and the seven council
seats, under the production wall cap. Nothing is recorded, so two runs read
different pages, and judges score shape and consistency, never a reference
answer.

A forecast that fails, or runs past the wall, is a report row, not a crash:
`classify_failure` says whose failure it was ("outside" only for a provider
outage), and the `finished_or_outside` judge fails the run on any failure of
ours (Q8). Each run prints one row per question: finished, side, members
voting, research and total seconds, the question, and the cause.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from evals.helpers.judge import markdown_link_urls
from evals.helpers.run import run
from evals.judges.e2e_deep_forecaster import OUTSIDE, judges
from models import ResearchLimitError

DATASET_PATH = Path(__file__).parent / "datasets" / "e2e_deep_forecaster.json"
# 2.5x the forecaster's wall cap (`ForecastLimits.wall_seconds`, 840 s). The
# task runs under the wall itself; this bounds a task that outlives the cap's
# cancel (`time_limits.run_under_time_limits` abandons such a task).
TIMEOUT_SECONDS = 2_100
OURS = "ours"
WALL_MESSAGE = "The forecast ran past its {seconds:g}-second wall."
logger = logging.getLogger("agent")


def classify_failure(error: BaseException) -> str:
    """Return whose failure a failed forecast was: "outside" or "ours" (brainstorm 2026Oct19 Q2).

    Outside only for a provider outage: every Brave search failed
    (`SearchUnavailableError`), every council member without a ballot failed
    on the provider's side (`QuorumError.outside`), or a model call's cause
    chain holds a connection error, a 429 or a 5xx. A refused request (another
    4xx), our time limits and the wall, and every check of ours are ours.
    """
    import openai

    # The outage threshold and the label are the council's and the judges',
    # imported, not copies that drift (review thread).
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


def forecast_output(
    state: dict[str, Any], step_seconds: dict[str, float]
) -> dict[str, Any]:
    """Return what the judges read from a finished forecast, and its report numbers."""
    from agents.deep_forecaster.consts.editorial import VOTE_LIST_HEADING
    from agents.deep_forecaster.evidence import render_passages

    claims, sources = state["claims"], state["sources"]
    # The writer's analysis, without the code-written vote list: its member
    # reasons are judgments, not facts a page states.
    analysis = state["answer"].split(VOTE_LIST_HEADING)[0].strip()
    cited = set(markdown_link_urls(analysis))
    return {
        "finished": True,
        "side": "",
        "cause": "",
        "answer": state["answer"],
        "analysis": analysis,
        "claims": [
            f"Claim {n}: {c.statement} (deadline: {c.deadline.isoformat()})"
            for n, c in enumerate(claims, start=1)
        ],
        "verdicts": [f"Claim {t.claim}: {t.verdict}" for t in state["tally"]],
        "passages": render_passages(claims, sources),
        "source_urls": [source.url for source in sources],
        "cited_sources": [
            {"title": source.title, "url": source.url, "text": source.text}
            for source in sources
            if source.url in cited
        ],
        "members_voting": len(state["ballots_round_1"]),
        "step_seconds": step_seconds,
    }


def failure_output(
    error: BaseException, step_seconds: dict[str, float]
) -> dict[str, Any]:
    """Return a failed forecast as a report row: whose failure, and what it said."""
    return {
        "finished": False,
        "side": classify_failure(error),
        "cause": f"{type(error).__name__}: {error}",
        "step_seconds": step_seconds,
    }


async def run_e2e_deep_forecaster(input: dict[str, Any]) -> dict[str, Any]:
    """Run the forecaster's graph live on one question, under the wall; a failure becomes the row."""
    from agents.deep_expert.graph import NO_CHECKPOINTER_CONFIG
    from agents.deep_forecaster.config import LIMITS
    from agents.deep_forecaster.graph import build_graph
    from agents.deep_forecaster.state import ForecastRun
    from agents.deep_forecaster.time_limits import run_under_time_limits
    from config import require_env

    # `ask_video` calls Gemini live, and Brave is not patched away.
    require_env(
        ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "BRAVE_SEARCH_KEY")
    )
    state: dict[str, Any] = {"question": input["query"]}
    # Bound to a name: a wall-capped row names the step the forecast was in
    # when the cap ended it, as `graph.forecast`'s 504 does (review thread).
    run = ForecastRun()
    step_seconds: dict[str, float] = {}
    started = time.monotonic()

    async def stream_steps() -> None:
        """Run the graph, merging each step's update into `state` and timing it."""
        last = started
        async for update in build_graph().astream(
            {"question": input["query"]},
            config=NO_CHECKPOINTER_CONFIG,
            context=run,
            stream_mode="updates",
        ):
            now = time.monotonic()
            for step, values in update.items():
                # Steps run one at a time, so the gap since the last update is
                # this step's time; the writer's rewrite adds to its first pass.
                step_seconds[step] = round(step_seconds.get(step, 0.0) + now - last, 1)
                state.update(values or {})
            last = now

    try:
        # The production wall (brainstorm review): a forecast the app would
        # end with a 504 is a failure here too, never a late "finished".
        _, capped = await run_under_time_limits(stream_steps(), LIMITS.wall_seconds)
        output = (
            failure_output(_wall_error(LIMITS.wall_seconds, run.step), step_seconds)
            if capped
            else forecast_output(state, step_seconds)
        )
    except Exception as error:  # noqa: BLE001 - a failed forecast is a report row (Q8)
        # The traceback, logged: a KeyError of ours must not hide behind the
        # one-line cause the report row shows (review thread).
        logger.exception("the forecast failed: %s", input["query"])
        output = failure_output(error, step_seconds)
    _print_row(input["query"], output, time.monotonic() - started)
    return output


def _wall_error(wall_seconds: float, step: str) -> ResearchLimitError:
    """Return the wall cap's error, naming the step the forecast was in.

    The empty `step` of a cap that ended nothing names no step, so it is
    left out (review thread).
    """
    message = WALL_MESSAGE.format(seconds=wall_seconds)
    if step:
        message += f" during this step: {step}"
    return ResearchLimitError(message)


def _print_row(query: str, output: dict[str, Any], total: float) -> None:
    """Print one report row: finished, side, voters, research and total seconds, cause."""
    print(
        f"{'finished' if output['finished'] else 'failed':8} "
        f"{output['side'] or '-':7} "
        f"voters {output.get('members_voting', '-')} "
        f"research {output['step_seconds'].get('research', '-')} s "
        f"total {total:.0f} s | {query} | {output['cause'] or '-'}"
    )


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="e2e_deep_forecaster",
            dataset_path=DATASET_PATH,
            task=run_e2e_deep_forecaster,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
