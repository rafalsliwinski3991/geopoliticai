"""reporter_fixed eval: a recorded conversation, the replies a user types at the outline, the report."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from evals.helpers.graph import load_messages, pending_pause
from evals.helpers.run import run
from evals.judges.reporter_fixed import judges

TIMEOUT_SECONDS = 600


async def run_reporter_fixed(input: dict[str, Any]) -> dict[str, Any]:
    """Build a report from a conversation, reading each typed reply the way the app does.

    Mirrors the orchestrator's reporter node (`has_researched_material`, then
    `build_transcript`) and `api._turn_input` (a reply is classified, then
    resumes the gate). A reply read as `new_question`, or typed when the
    outline no longer waits, stops the replies there.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agents.reporter import (
        build_graph,
        build_initial_reporter_state,
        build_transcript,
        classify_resume_intent,
        has_researched_material,
    )
    from agents.reporter.consts.messages import NO_MATERIAL_NOTICE

    messages = load_messages(input["messages"])
    transcript = build_transcript(messages)
    if not has_researched_material(messages):
        # The app refuses here, before the subgraph and with no model call.
        return {
            "transcript": transcript,
            "reply_actions": [],
            "outcome": "refused",
            "outline": [],
            "notice": NO_MATERIAL_NOTICE,
            "report": "",
        }
    graph = build_graph(checkpointer=InMemorySaver())
    config: dict[str, Any] = {"configurable": {"thread_id": f"eval-{uuid4()}"}}
    result = await graph.ainvoke(build_initial_reporter_state(transcript), config)
    actions: list[str] = []
    for reply in input.get("replies", []):
        pause = await pending_pause(graph, config)
        if pause is None:
            break
        intent = await classify_resume_intent(reply, pause)
        actions.append(intent.action)
        if intent.action == "new_question":
            break
        result = await graph.ainvoke(
            Command(
                resume={"action": intent.action, "instruction": intent.instruction}
            ),
            config,
        )
    paused = await pending_pause(graph, config) is not None
    return {
        "transcript": transcript,
        "reply_actions": actions,
        "outcome": read_outcome(result, paused=paused),
        "outline": list(result["outline"]),
        "notice": result["notice"],
        "report": result["report"],
    }


def read_outcome(result: dict[str, Any], *, paused: bool) -> str:
    """Name how a report run ended: open, report, cancelled, capped, or refused."""
    from agents.reporter.consts.messages import CANCELLED_NOTICE, REVISION_CAP_NOTICE

    if paused:
        return "open"
    if result["report"]:
        return "report"
    if result["notice"] == CANCELLED_NOTICE:
        return "cancelled"
    if result["notice"] == REVISION_CAP_NOTICE:
        return "capped"
    # The outline refused: no material, or the model's own notice.
    return "refused"


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="reporter_fixed",
            task=run_reporter_fixed,
            judges=judges(),
            # Two outline rounds (120 s each) plus write (300 s), with room to spare.
            timeout=TIMEOUT_SECONDS,
        )
    )
