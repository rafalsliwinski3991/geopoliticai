"""orchestrator_fixed eval: the classifier alone routes and rewrites recorded conversations."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.helpers.graph import load_messages
from evals.helpers.run import run
from evals.judges.orchestrator_fixed import judges


async def run_orchestrator_fixed(input: dict[str, Any]) -> dict[str, Any]:
    """Classify a conversation's last turn: where it goes, and its standalone rewrite.

    Only the `classify` node runs (brainstorm 2026Oct21 R1.3): no chat answer,
    no research. Agent imports are function-local: `agents.*.graph` calls
    `init_tracing()` at import, which must happen after `run` has loaded the
    environment, and importing agents at module scope would drag the stack
    into unit tests.
    """
    from agents.orchestrator.nodes.classify import classify

    decision = await classify(
        {"messages": load_messages(input["messages"])}, _drop_progress
    )
    return {
        "destination": decision["destination"],
        "standalone_query": decision["standalone_query"],
    }


def _drop_progress(event: Any) -> None:
    """Ignore the node's progress frame: no browser is listening."""


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="orchestrator_fixed",
            task=run_orchestrator_fixed,
            judges=judges(),
        )
    )
