"""Delegation to the reporter agent (graph node 2c)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from agents.orchestrator.state import OrchestratorState
from agents.reporter import (
    build_initial_reporter_state,
    build_transcript,
    has_researched_material,
)
from agents.reporter import graph as reporter_graph
from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE

logger = logging.getLogger(__name__)


async def reporter(state: OrchestratorState, writer: StreamWriter) -> dict[str, Any]:
    """Run the compiled reporter subgraph over the whole thread.

    Invoked here, not handed to `add_node`, for the same reason as the expert:
    `ReporterState` shares no key with `OrchestratorState`, and LangGraph 1.0.1
    would run the child on empty input and discard its result with no error.

    This body re-runs from its first line on every resume, so it holds no model
    call: `has_researched_material` and `build_transcript` are pure, and
    LangGraph resumes the child from the parent's checkpoint namespace rather
    than restarting it on the input supplied here (measured — a full approve
    cycle left the outline call count at 1).

    **The `notice` emission is what keeps the no-model-call paths from ending as
    a 502.** A refusal, a cancel and a spent revision budget all end the turn
    with real text for the user, but none of them streams anything through
    `stream_mode="messages"`, so without this the run would produce no output at
    all and `_generate` would report `502 "The model returned an empty answer."`
    for what is actually a successful, deliberate outcome.

    It cannot double-emit the report, and not because of any timing: the
    emission is guarded on `report` being empty, and on the approve path it is
    not. On a *revise* resume the child pauses again inside `ainvoke`, so
    execution never reaches this line at all. That is also why the emission sits
    below the `ainvoke` rather than above it — a `writer` call above a line that
    can pause re-fires on every resume round (measured).
    """
    if not has_researched_material(state["messages"]):
        # Q5, decided here rather than in the outline prompt. The subgraph is
        # never invoked: no model call, no interrupt, no gate. The refusal is a
        # pure function of the thread, so it cannot vary run to run.
        logger.info("reporter: refusing, no researched material in thread")
        writer({"type": "notice", "text": NO_MATERIAL_NOTICE})
        return {"messages": [AIMessage(NO_MATERIAL_NOTICE)]}
    transcript = build_transcript(state["messages"])
    result = await reporter_graph.ainvoke(build_initial_reporter_state(transcript))
    report: str = result.get("report") or ""
    text = report or result.get("notice") or CANCELLED_NOTICE
    if not report:
        # `text` here can be model-produced (the outline node's `notice`), which
        # is why it travels as a `notice` event rather than as a `progress` one:
        # `api.py` turns a notice into a token, so it passes through the
        # `MAX_ANSWER_CHARS` accounting like any other answer. Only hardcoded
        # literals are ever forwarded to the browser verbatim (§1).
        writer({"type": "notice", "text": text})
    logger.info(
        "reporter: %d transcript chars, %d sections, %d report chars",
        len(transcript),
        len(result.get("outline") or []),
        len(report),
    )
    return {"messages": [AIMessage(text)]}
