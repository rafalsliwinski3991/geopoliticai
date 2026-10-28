"""Stand-ins for every outside call a turn makes, with a configurable delay.

Everything between the HTTP request and these seams is the production code:
FastAPI, auth, the rate limit, `quota.charge_turn`, the orchestrator and expert
graphs, LangGraph streaming and checkpointing, and the page reader's
trafilatura extraction. Only these are replaced:

- the OpenAI clients (`llm._build_client`, `llm._build_structured_client`),
- one Brave request (`search._brave_batch`),
- the page fetch transport (`search.build_fetch_client`),
- the Django-owned tables (`db/web/sql.py`'s helpers, as `api` and `quota`
  import them), and Postgres for the checkpointer (an `InMemorySaver`).

So a run costs nothing, needs no key or database, and gives the same answers
every time; its timings measure this service, plus the delays set here.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

import api
import llm
import quota
import search
from agents.orchestrator import build_graph
from config import LLMSettings
from db.web.sql import ThreadRow, quota_day
from loadtests.turns import RESEARCH_KEYWORD
from models import Candidate, SourcePolicy

CHAT_ANSWER = "Hello! Ask me about any geopolitical question and I will research it."
# Every non-routing call (the expert's answer, the supervisor's footer) streams
# this, one word per chunk.
ANSWER_TEXT = (
    "Load-test answer. The situation remains tense, with both sides signalling "
    "readiness to talk while reinforcing their positions, according to the "
    "sources read [1](https://www.bbc.com/loadtest/0). Analysts expect no "
    "breakthrough before the next summit [2](https://www.dw.com/loadtest/0)."
)
# Brave results per batch, one per domain: three batches give twelve
# candidates, which the expert cuts to its `RETRIEVAL.fetch_candidates`.
RESULTS_PER_BATCH = 4
ARTICLE_PARAGRAPH = (
    "Diplomats from both capitals met again this week to discuss the ceasefire "
    "line, the exchange of prisoners and the reopening of the border crossings. "
    "Officials said the talks were constructive but that no agreement had been "
    "reached on the sequencing of troop withdrawals or on monitoring. "
)
ARTICLE_PARAGRAPHS = 12


@dataclass(frozen=True)
class LatencyProfile:
    """How long each faked outside call takes, in seconds."""

    llm_first_token: float = 0.0
    llm_per_token: float = 0.0
    search: float = 0.0
    fetch: float = 0.0
    db: float = 0.0


class FakeChatModel(BaseChatModel):
    """A chat model that answers from a fixed script after the profile's delay.

    With tools bound it is the supervisor: a query naming `RESEARCH_KEYWORD`
    becomes a `run_expert` call, anything else a chat answer. Unbound it is
    every other caller and streams `ANSWER_TEXT`.
    """

    first_token_delay: float = 0.0
    per_token_delay: float = 0.0
    tools_bound: bool = False

    @property
    def _llm_type(self) -> str:
        return "loadtest-fake"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        """Return a copy that routes like the supervisor; the tools are not read."""
        return self.model_copy(update={"tools_bound": True})

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        if not self.tools_bound:
            return AIMessage(ANSWER_TEXT)
        query = next(
            (m.text for m in reversed(messages) if isinstance(m, HumanMessage)), ""
        )
        if RESEARCH_KEYWORD not in query.lower():
            return AIMessage(CHAT_ANSWER)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {"query": query},
                    "id": f"call-{uuid4().hex}",
                    "type": "tool_call",
                }
            ],
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        await asyncio.sleep(self.first_token_delay)
        return self._generate(messages)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        await asyncio.sleep(self.first_token_delay)
        reply = self._reply(messages)
        if reply.tool_calls:
            # LangChain streams even an `ainvoke` when a stream handler is
            # attached, as `stream_mode="messages"` attaches one: the call
            # must survive as a chunk.
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"]),
                            "id": call["id"],
                            "index": index,
                            "type": "tool_call_chunk",
                        }
                        for index, call in enumerate(reply.tool_calls)
                    ],
                )
            )
            return
        words = reply.text.split(" ")
        for index, word in enumerate(words):
            if index:
                await asyncio.sleep(self.per_token_delay)
            text = word if index == len(words) - 1 else f"{word} "
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
            if run_manager is not None:
                await run_manager.on_llm_new_token(text, chunk=chunk)
            yield chunk


def build_article_html(title: str) -> str:
    """Return a news-article page long enough to pass the expert's minimum."""
    # Numbered: trafilatura drops a paragraph that repeats an earlier one.
    body = "".join(
        f"<p>Update {number}. {ARTICLE_PARAGRAPH}</p>"
        for number in range(1, ARTICLE_PARAGRAPHS + 1)
    )
    return (
        f'<!doctype html><html lang="en"><head><title>{title}</title>'
        '<meta name="author" content="Load Test Desk"></head>'
        f"<body><article><h1>{title}</h1>{body}</article></body></html>"
    )


@dataclass
class InMemoryWebDb:
    """The Django-owned tables a turn touches, kept in this process.

    Each method has the signature of its namesake in `db/web/sql.py` and the
    same rule: a conditional quota upsert that refuses past the limit, a refund
    that never goes below zero, and a thread that belongs to its first claimer.
    """

    delay: float = 0.0
    owners: dict[str, tuple[int, str, datetime]] = field(default_factory=dict)
    used: dict[tuple[int, date], int] = field(default_factory=dict)
    site_used: dict[date, int] = field(default_factory=dict)

    async def claim_thread(
        self, pool: Any, *, thread_id: str, user_id: int, title: str
    ) -> bool:
        """Create the thread if new; report whether this user owns it."""
        await asyncio.sleep(self.delay)
        self.owners.setdefault(thread_id, (user_id, title, datetime.now(UTC)))
        return self.owners[thread_id][0] == user_id

    async def owns_thread(self, pool: Any, *, thread_id: str, user_id: int) -> bool:
        """Report whether this thread exists and belongs to this user."""
        await asyncio.sleep(self.delay)
        owner = self.owners.get(thread_id)
        return owner is not None and owner[0] == user_id

    async def list_threads(self, pool: Any, *, user_id: int) -> list[ThreadRow]:
        """Return this user's threads, newest first."""
        await asyncio.sleep(self.delay)
        rows = [
            ThreadRow(id=thread_id, title=title, created_at=created_at)
            for thread_id, (owner, title, created_at) in self.owners.items()
            if owner == user_id
        ]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)

    async def quota_used(self, pool: Any, *, user_id: int) -> int:
        """Return the units this user spent today."""
        await asyncio.sleep(self.delay)
        return self.used.get((user_id, quota_day()), 0)

    async def increment_quota(
        self, pool: Any, *, user_id: int, day: date, limit: int, cost: int = 1
    ) -> int | None:
        """Spend `cost` of this user's units; None when they do not fit."""
        await asyncio.sleep(self.delay)
        spent = self.used.get((user_id, day), 0) + cost
        if cost <= 0 or spent > limit:
            return None
        self.used[(user_id, day)] = spent
        return spent

    async def increment_site_quota(
        self, pool: Any, *, limit: int, cost: int = 1
    ) -> int | None:
        """Spend `cost` of the site's units; None when they do not fit."""
        await asyncio.sleep(self.delay)
        day = quota_day()
        spent = self.site_used.get(day, 0) + cost
        if cost <= 0 or spent > limit:
            return None
        self.site_used[day] = spent
        return spent

    async def refund_quota(
        self, pool: Any, *, user_id: int, day: date, cost: int
    ) -> None:
        """Give `cost` units back, never below zero."""
        await asyncio.sleep(self.delay)
        if cost > 0 and (user_id, day) in self.used:
            self.used[(user_id, day)] = max(0, self.used[(user_id, day)] - cost)


@contextmanager
def fake_backend(profile: LatencyProfile) -> Iterator[InMemoryWebDb]:
    """Point `api.app` at the fakes for the duration; yield the fake tables.

    The rate-limit window, the refund cap and the turn locks start empty, so
    one run never inherits another's counters.
    """
    db = InMemoryWebDb(delay=profile.db)

    def build_model(settings: LLMSettings) -> FakeChatModel:
        return FakeChatModel(
            first_token_delay=profile.llm_first_token,
            per_token_delay=profile.llm_per_token,
        )

    async def brave_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        await asyncio.sleep(profile.search)
        return [
            Candidate(
                title=f"{domain} report",
                url=f"https://www.{domain}/loadtest/0",
                domain=domain,
            )
            for domain in domains[:RESULTS_PER_BATCH]
        ]

    async def serve_page(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(profile.fetch)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=build_article_html(str(request.url)),
        )

    def build_fetch_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=search.FETCH_HEADERS, transport=httpx.MockTransport(serve_page)
        )

    with ExitStack() as stack:
        stack.enter_context(
            patch.dict(os.environ, {"BRAVE_SEARCH_KEY": "loadtest-fake-key"})
        )
        stack.enter_context(patch.object(llm, "_build_client", build_model))
        stack.enter_context(patch.object(llm, "_build_structured_client", build_model))
        stack.enter_context(patch.object(search, "_brave_batch", brave_batch))
        stack.enter_context(
            patch.object(search, "build_fetch_client", build_fetch_client)
        )
        for name in ("claim_thread", "owns_thread", "list_threads", "quota_used"):
            stack.enter_context(patch.object(api, name, getattr(db, name)))
        for name in (
            "quota_used",
            "increment_quota",
            "increment_site_quota",
            "refund_quota",
        ):
            stack.enter_context(patch.object(quota, name, getattr(db, name)))
        stack.enter_context(
            patch.object(
                api,
                "graph",
                build_graph(checkpointer=InMemorySaver(), store=InMemoryStore()),
            )
        )
        stack.enter_context(patch.object(api.app.state, "pool", None, create=True))
        stack.enter_context(patch.dict(api._rate_limit_store, clear=True))
        stack.enter_context(patch.dict(quota._refunded_units, clear=True))
        stack.enter_context(patch.dict(quota._turn_locks, clear=True))
        yield db
