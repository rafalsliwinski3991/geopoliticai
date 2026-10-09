"""Forecast backtest: forecasts made as of a past date, scored against what happened (F6).

Each example is a question that resolved between 2026-07-01 and 2026-09-30.
Its hand-written sources state only what was public on its `as_of` date and
are synthetic (any resemblance to real reporting on that date is incidental);
a future recording of real, as-of-public articles can replace them. The forecast runs as of `as_of` (`ForecastRun.today`), so its claims
fall after that date. A leakage probe asks every model that can vote (each
seat's own model, 7 models) the question with no sources (the OpenRouter
models' training cutoffs are unpublished, and gpt-5-mini's alone predates
every question):
- a model that already knows the outcome fails
  `outcome_unknown_without_sources`, and that question must be replaced;
- a model that cannot answer at all (an error, a rate limit, a retired id)
  makes the whole run invalid (`ProbeUnavailableError` exits non-zero), so a
  hidden probe failure can never read as ignorance (review thread, #150).

The judges score only the example's `focal_claim` (claim number): the other
claims' outcomes are not in the dataset, so scoring them would make the model
judge guess (review thread, #150). Two questions now is a smoke signal, not a
measurement.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from evals.deep_forecaster import TIMEOUT_SECONDS, forecast_output
from evals.helpers.graph import load_sources, recorded_sources
from evals.helpers.run import run
from evals.judges.forecast_backtest import judges

DATASET_PATH = Path(__file__).parent / "datasets" / "forecast_backtest.json"


class ProbeUnavailableError(Exception):
    """One probing model could not answer at all, so the run proves nothing (F6)."""


LEAK_PROBE_PROMPT = """Answer from your own knowledge only; you have no \
sources. If you know how the following turned out, state the outcome and when \
it happened. If you do not know, reply exactly: I do not know how this turned out."""


async def leak_probe(query: str) -> str:
    """Ask every model that can vote the question with no sources; no reply may know the outcome.

    That is each seat's own model (plan unit 04); every seat is a paid model
    (user decision 2026-10-08), so no other model can vote.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.deep_forecaster.config import COUNCIL, Seat
    from agents.deep_forecaster.council import member_client

    async def ask(label: str, seat: Seat, model: str) -> str:
        try:
            reply = await member_client(seat, model).ainvoke(
                [SystemMessage(LEAK_PROBE_PROMPT), HumanMessage(query)]
            )
            return f"{label}: {reply.text}"
        except Exception as exc:  # noqa: BLE001 - an unavailable model cannot leak
            return f"{label}: unavailable ({type(exc).__name__})"

    asks = [
        ask(f"Member {member}", seat, seat.model)
        for member, seat in enumerate(COUNCIL, start=1)
    ]
    replies = await asyncio.gather(*asks)
    dead = [line.split(":")[0] for line in replies if "unavailable" in line]
    if dead:
        raise ProbeUnavailableError(
            "the leakage probe could not reach: " + ", ".join(dead)
        )
    return "\n\n".join(replies)


async def run_forecast_backtest(input: dict[str, Any]) -> dict[str, Any]:
    """Forecast one resolved question as of its `as_of` date, then probe for leakage."""
    from agents.deep_expert.graph import NO_CHECKPOINTER_CONFIG
    from agents.deep_forecaster.graph import build_graph
    from agents.deep_forecaster.state import ForecastRun
    from config import require_env

    require_env(("GEMINI_API_KEY",))
    sources = load_sources(input["sources"])
    with recorded_sources(lambda: sources):
        state = await build_graph().ainvoke(
            {"question": input["query"]},
            config=NO_CHECKPOINTER_CONFIG,
            context=ForecastRun(today=date.fromisoformat(input["as_of"])),
        )
    return {**forecast_output(state), "leak_probe": await leak_probe(input["query"])}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="forecast_backtest",
            dataset_path=DATASET_PATH,
            task=run_forecast_backtest,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
