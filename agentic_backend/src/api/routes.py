"""Health and thread routes, and their response models."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import (
    BaseModel,
    ConfigDict,
)

from agents.orchestrator import (
    build_runtime_config,
)
from api.auth import Identity, require_identity
from api.rate_limit import enforce_rate_limit
from db.web.sql import (
    MAX_THREAD_ID_LENGTH,
    THREAD_ID_PATTERN,
    is_staff,
    list_threads,
    owns_thread,
    quota_used,
)
from shared.config import (
    DAILY_RESEARCH_TURNS,
    FOOTER_PREFIX,
    bind_log_context,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

ThreadIdPath = Annotated[
    str,
    Path(min_length=1, max_length=MAX_THREAD_ID_LENGTH, pattern=THREAD_ID_PATTERN),
]


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    """Return a simple health status."""
    return {"status": "ok"}


class ThreadSummary(BaseModel):
    """One conversation in the sidebar list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime


class QuotaView(BaseModel):
    """Today's research turns used against the daily limit."""

    used: int
    limit: int


class ThreadList(BaseModel):
    """The caller's conversations and today's quota."""

    threads: list[ThreadSummary]
    quota: QuotaView


class ChatMessage(BaseModel):
    """One message of a stored conversation."""

    role: Literal["user", "assistant"]
    text: str


class ThreadMessages(BaseModel):
    """One stored conversation."""

    thread_id: str
    messages: list[ChatMessage]


async def _thread_messages(graph: Any, thread_id: str) -> list[ChatMessage]:
    """Read one conversation live from the checkpointer (Q6).

    The checkpointer's message text lives in msgpack-serialized BYTEA, so the
    only thing that can read it is code holding the graph — never an admin
    pointed at the table (brainstorm §2.4). `aget_state` is that code.
    """
    if getattr(graph, "checkpointer", None) is None:
        return []
    snapshot = await graph.aget_state(build_runtime_config(thread_id=thread_id))
    rendered: list[ChatMessage] = []
    for msg in snapshot.values.get("messages", []):
        if msg.type == "human":
            rendered.append(ChatMessage(role="user", text=msg.text))
        elif isinstance(msg, ToolMessage):
            text = (
                msg.artifact.get("text", msg.content)
                if isinstance(msg.artifact, dict)
                else msg.content
            )
            rendered.append(ChatMessage(role="assistant", text=str(text)))
        elif isinstance(msg, AIMessage) and msg.text and not msg.tool_calls:
            if msg.text.startswith(FOOTER_PREFIX) and rendered:
                rendered[-1].text += msg.text
            else:
                rendered.append(ChatMessage(role="assistant", text=msg.text))
    return rendered


@router.get("/threads")
async def list_threads_endpoint(
    request: Request, identity: Identity = Depends(require_identity)
) -> ThreadList:
    """Return the caller's conversations and today's quota, for the sidebar."""
    bind_log_context(user_id=identity.user_id)
    pool = request.app.state.pool
    return ThreadList(
        threads=[
            ThreadSummary.model_validate(row)
            for row in await list_threads(pool, user_id=identity.user_id)
        ],
        quota=QuotaView(
            used=await quota_used(pool, user_id=identity.user_id),
            limit=DAILY_RESEARCH_TURNS,
        ),
    )


@router.get("/threads/{thread_id}")
async def read_thread_endpoint(
    thread_id: ThreadIdPath,
    request: Request,
    identity: Identity = Depends(require_identity),
) -> ThreadMessages:
    """Return one of the caller's own conversations."""
    bind_log_context(thread_id=thread_id, user_id=identity.user_id)
    # Rate-limited like the streaming route: this reads a checkpoint and
    # deserializes an entire conversation, so it is not free. The daily quota
    # (unit 6) deliberately does not cover it: reading your own history must
    # not cost research turns.
    enforce_rate_limit(request, identity)
    pool = request.app.state.pool
    if not await owns_thread(pool, thread_id=thread_id, user_id=identity.user_id):
        raise HTTPException(status_code=403, detail="That conversation is not yours.")
    return ThreadMessages(
        thread_id=thread_id,
        messages=await _thread_messages(request.app.state.graph, thread_id),
    )


@router.get("/admin/threads/{thread_id}")
async def admin_read_thread_endpoint(
    thread_id: ThreadIdPath,
    request: Request,
    identity: Identity = Depends(require_identity),
) -> ThreadMessages:
    """Return any conversation, for a staff user (Q6, Q17b)."""
    bind_log_context(thread_id=thread_id, user_id=identity.user_id)
    enforce_rate_limit(request, identity)
    # Re-read from Postgres rather than trusting a claim: a token minted before
    # staff was revoked stays valid for its full 15 minutes otherwise.
    if not await is_staff(request.app.state.pool, user_id=identity.user_id):
        raise HTTPException(status_code=403, detail="Staff only.")
    return ThreadMessages(
        thread_id=thread_id,
        messages=await _thread_messages(request.app.state.graph, thread_id),
    )
