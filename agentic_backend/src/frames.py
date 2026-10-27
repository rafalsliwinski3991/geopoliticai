"""The chat stream's frames as typed models, and the one place they are encoded.

Nodes build `ProgressFrame` and `NoticeEvent` and hand them to their
`StreamWriter`; `api.py` builds the rest. `encode_frame` writes
`json.dumps(model_dump(exclude_none=True))`, which is byte-identical to the
hand-built dicts it replaced (brainstorm 2026Oct22 Q5): fields are declared in
the order those dicts wrote them, and an unset optional field is left out
rather than written as null. The one exception is `PauseFrame`, which inherits
`OutlinePause`'s fields and so writes `type` last. Studio carries these objects too: langgraph_api
serializes a Pydantic object through `model_dump()`.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from models import OutlinePause


class ProgressFrame(BaseModel):
    """One step label. Every label is a literal in an agent's `consts/progress.py`."""

    model_config = ConfigDict(frozen=True)

    type: Literal["progress"] = "progress"
    node: str
    label: str


class NoticeEvent(BaseModel):
    """A node's whole answer, which `api.py` streams as tokens; never sent as is."""

    model_config = ConfigDict(frozen=True)

    type: Literal["notice"] = "notice"
    text: str


class TokenFrame(BaseModel):
    """A slice of the answer text."""

    type: Literal["token"] = "token"
    content: str


class PauseFrame(OutlinePause):
    """The outline a paused report waits on; built from the gate's `interrupt()` payload."""

    type: Literal["pause"] = "pause"


class ResultFrame(BaseModel):
    """The turn's whole answer, once every token was sent."""

    type: Literal["result"] = "result"
    output: str
    kind: Literal["report", "answer"]
    truncated: bool


class ErrorFrame(BaseModel):
    """A failed turn: the HTTP status the failure maps to, and the message shown."""

    type: Literal["error"] = "error"
    status: int
    message: str


Frame = ProgressFrame | TokenFrame | PauseFrame | ResultFrame | ErrorFrame
# A node's custom stream event. Validates a frame object or the plain dict a
# test fake writes; anything else is not a node event (`api._astream_answer`).
NODE_EVENT: TypeAdapter[ProgressFrame | NoticeEvent] = TypeAdapter(
    Annotated[ProgressFrame | NoticeEvent, Field(discriminator="type")]
)


def encode_frame(frame: Frame) -> str:
    """Return one SSE data frame."""
    return f"data: {json.dumps(frame.model_dump(exclude_none=True))}\n\n"
