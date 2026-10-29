"""deep_forecaster_live eval: the whole deep forecaster, live, on questions users asked.

Brainstorm 2026Oct19 (Q5-Q8): the only forecaster eval. Five questions from
the Phoenix traces, typed as users typed them, each run once with live Brave
searches, live page reading, Gemini's video reading and the seven council
seats, under the production wall cap. Nothing is recorded, so two runs read
different pages, and judges score shape and consistency, never a reference
answer.

A forecast that fails, or runs past the wall, is a report row, not a crash:
`evals.helpers.live.classify_failure` says whose failure it was ("outside" only for a provider
outage), and the `finished_or_outside` judge fails the run on any failure of
ours (Q8). The runner prints one row per question: finished, side, members
voting, research and total seconds, the question, and the cause.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from evals.helpers.judge import markdown_link_urls
from evals.helpers.live import build_failure_row
from evals.helpers.run import run
from evals.judges.deep_forecaster_live import judges
from shared.errors import ResearchLimitError

# 2.5x the forecaster's wall cap (`ForecastLimits.wall_seconds`, 840 s). The
# task runs under the wall itself; this bounds a task that outlives the cap's
# cancel (`capped_run.run_under_time_limits` abandons such a task).
TIMEOUT_SECONDS = 2_100
WALL_MESSAGE = "The forecast ran past its {seconds:g}-second wall."
logger = logging.getLogger("agent")


def forecast_output(
    state: dict[str, Any], step_seconds: dict[str, float]
) -> dict[str, Any]:
    """Return what the judges read from a finished forecast, and its report numbers."""
    from agents.deep_forecaster.consts.editorial import WORDS
    from agents.deep_forecaster.render import render_passages

    claims, sources = state["claims"], state["sources"]
    # The writer's analysis, without the code-written vote list: its member
    # reasons are judgments, not facts a page states.
    # The heading is in the language the question was asked in.
    vote_list = "|".join(re.escape(words.vote_list_heading) for words in WORDS.values())
    analysis = re.split(vote_list, state["answer"])[0].strip()
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


async def run_deep_forecaster_live(input: dict[str, Any]) -> dict[str, Any]:
    """Run the forecaster's graph live on one question, under the wall; a failure becomes the row."""
    from agents.capped_run import NO_CHECKPOINTER_CONFIG, run_under_time_limits
    from agents.deep_forecaster.config import LIMITS
    from agents.deep_forecaster.graph import build_graph
    from agents.deep_forecaster.state import ForecastRun

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
            build_failure_row(_wall_error(LIMITS.wall_seconds, run.step), step_seconds)
            if capped
            else forecast_output(state, step_seconds)
        )
    except Exception as error:  # noqa: BLE001 - a failed forecast is a report row (Q8)
        # The traceback, logged: a KeyError of ours must not hide behind the
        # one-line cause the report row shows (review thread).
        logger.exception("the forecast failed: %s", input["query"])
        output = build_failure_row(error, step_seconds)
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


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="deep_forecaster_live",
            task=run_deep_forecaster_live,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
            # `ask_video` calls Gemini live.
            extra_env_vars=("GEMINI_API_KEY",),
        )
    )
