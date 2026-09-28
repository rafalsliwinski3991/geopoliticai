"""e2e eval: multi-turn conversations through the orchestrator, typed replies included."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from evals.helpers.graph import load_sources, pending_pause, recorded_sources
from evals.helpers.run import run
from evals.judges.e2e import judges
from models import Source

DATASET_PATH = Path(__file__).parent / "datasets" / "e2e.json"
# Two expert/outline rounds plus classifier calls in one task.
TIMEOUT_SECONDS = 900


async def run_e2e(input: dict[str, Any]) -> dict[str, Any]:
    """Play every turn on one thread and record what happened on each."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agents.orchestrator import (
        build_graph,
        build_initial_orchestrator_state,
        build_runtime_config,
    )
    from agents.reporter import classify_resume_intent

    graph = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id=f"eval-{uuid4()}")
    # A plain local read at call time: `recorded_sources` re-invokes its
    # callable on every retrieval, and the closure below closes over the
    # variable, not a value.
    current: list[Source] | None = None
    turns: list[dict[str, Any]] = []
    with recorded_sources(lambda: current):
        for turn in input["turns"]:
            current = load_sources(turn["sources"]) if "sources" in turn else None
            text: str = turn["text"]
            record: dict[str, Any] = {}
            # Mirrors `api._turn_input`: text typed at a pause is a reply unless
            # the classifier calls it a new question.
            pause = await pending_pause(graph, config)
            graph_input: Any = build_initial_orchestrator_state(text)
            if pause is not None:
                intent = await classify_resume_intent(text, pause)
                record["resume_action"] = intent.action
                if intent.action != "new_question":
                    graph_input = Command(
                        resume={
                            "action": intent.action,
                            "instruction": intent.instruction,
                        }
                    )
            result = await graph.ainvoke(graph_input, config)
            if not isinstance(graph_input, Command):
                record["destination"] = result["destination"]
            after = await pending_pause(graph, config)
            if after is not None:
                record["pause"] = {"outline": list(after.get("outline") or [])}
            else:
                record["answer"] = result["messages"][-1].text
            turns.append(record)
    return {"turns": turns}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="e2e",
            dataset_path=DATASET_PATH,
            task=run_e2e,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
