"""The human approval gate (graph node 2). The only `interrupt()` in this repo."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from agents.reporter.config import MAX_REVISION_ROUNDS
from agents.reporter.consts.messages import CANCELLED_NOTICE
from agents.reporter.state import GateAction, ReporterState

logger = logging.getLogger(__name__)


def _decode(reply: Any) -> tuple[GateAction, str]:
    """Read `{action, instruction}` out of whatever the resume carried.

    The delivery layer always sends the dict form. A bare string is accepted so
    that a human typing into Studio's resume box gets the obvious behaviour —
    typing at an outline means revise — instead of a crash.
    """
    if isinstance(reply, dict):
        action = reply.get("action")
        instruction = str(reply.get("instruction") or "")
    else:
        action = "revise"
        instruction = str(reply or "")
    if action == "approve":
        return "approve", ""
    if action == "cancel":
        return "cancel", ""
    return "revise", instruction


async def gate(state: ReporterState) -> dict[str, Any]:
    """Pause with the outline and record the decision the user sent back.

    Everything before `interrupt()` re-runs on every resume — stated in
    `interrupt()`'s own docstring at `langgraph/types.py:396-473` and confirmed
    by probe — so nothing expensive may go above this line. Building the payload
    from state is the whole body.

    **This node takes no `writer` deliberately.** A progress event emitted above
    `interrupt()` would re-fire on every resume round, and one emitted below it
    would fire after the decision is already made. The pause itself reaches the
    browser through `__interrupt__` on `stream_mode="updates"`, which is a
    different channel for a reason: it is state the checkpointer holds, not a
    transient notification.
    """
    reply = interrupt(
        {
            # Deliberately no "kind" key. The SSE frame this becomes is already
            # typed `pause`, and `result` frames use "kind" for report/answer.
            # One name meaning two things, on frames the same client handler
            # reads, is a trap. `test_api.py` asserts the frame's shape has no
            # `kind`, so this stays enforced rather than merely intended.
            "outline": list(state["outline"]),
            "notice": state["notice"],
            "revisions_used": state["revisions"],
            "revisions_allowed": MAX_REVISION_ROUNDS,
        }
    )
    action, instruction = _decode(reply)
    logger.info("gate: decision=%s", action)
    if action == "revise":
        return {
            "decision": "revise",
            "instruction": instruction,
            "revisions": state["revisions"] + 1,
            "notice": "",
        }
    if action == "cancel":
        return {"decision": "cancel", "instruction": "", "notice": CANCELLED_NOTICE}
    return {"decision": "approve", "instruction": "", "notice": ""}
