from datetime import date

import pytest
from langchain_core.messages import HumanMessage

import api
from agents.expert.consts.sources import EXPERT_SOURCES
from loadtests.fakes import (
    CHAT_ANSWER,
    FakeChatModel,
    InMemoryWebDb,
    LatencyProfile,
    build_article_html,
    fake_backend,
)
from loadtests.scenarios import RESEARCH_QUERY
from search import _extract_page

POOL = None
DAY = date(2026, 10, 27)
LIMIT = 2


def test_the_supervisor_fake_routes_a_research_query_to_the_expert() -> None:
    """The research turn must reach `run_expert`, or the load never touches
    search, page extraction, or the quota charge."""
    # Arrange
    supervisor = FakeChatModel().bind_tools([])

    # Act
    reply = supervisor.invoke([HumanMessage(RESEARCH_QUERY)])

    # Assert
    assert [call["name"] for call in reply.tool_calls] == ["run_expert"]


def test_the_supervisor_fake_answers_small_talk_itself() -> None:
    """A query without the research keyword is a free chat turn."""
    # Arrange
    supervisor = FakeChatModel().bind_tools([])

    # Act
    reply = supervisor.invoke([HumanMessage("Hello there")])

    # Assert
    assert (reply.text, reply.tool_calls) == (CHAT_ANSWER, [])


@pytest.mark.anyio
async def test_a_streamed_routing_call_keeps_its_tool_call() -> None:
    """Under `stream_mode="messages"` LangChain streams the supervisor's
    `ainvoke`; a fake that streamed only text would lose the call, and every
    research turn would fail as an empty chat answer."""
    # Arrange
    supervisor = FakeChatModel().bind_tools([])
    chunks = [
        chunk async for chunk in supervisor.astream([HumanMessage(RESEARCH_QUERY)])
    ]

    # Act
    merged = sum(chunks[1:], chunks[0])

    # Assert
    assert [call["name"] for call in merged.tool_calls] == ["run_expert"]


@pytest.mark.anyio
async def test_the_fake_article_survives_extraction() -> None:
    """A page trafilatura cuts below the expert's minimum is dropped, and a turn
    with no page left fails with no sources."""
    # Arrange
    html = build_article_html("Ceasefire talks")

    # Act
    page = await _extract_page(html)

    # Assert
    assert page.text is not None
    assert len(page.text) >= EXPERT_SOURCES.min_source_chars


@pytest.mark.anyio
async def test_the_fake_quota_refuses_a_unit_past_the_limit() -> None:
    """Like the conditional upsert, the fake must refuse at the cap, or a load
    run would never show the 429s production gives."""
    # Arrange
    db = InMemoryWebDb()
    for _ in range(LIMIT):
        await db.increment_quota(POOL, user_id=1, day=DAY, limit=LIMIT)

    # Act
    refused = await db.increment_quota(POOL, user_id=1, day=DAY, limit=LIMIT)

    # Assert
    assert refused is None


@pytest.mark.anyio
async def test_a_fake_refund_never_goes_below_zero() -> None:
    """A refund larger than what was spent leaves the counter at zero, as the
    SQL's GREATEST does."""
    # Arrange
    db = InMemoryWebDb()
    await db.increment_quota(POOL, user_id=1, day=DAY, limit=LIMIT)

    # Act
    await db.refund_quota(POOL, user_id=1, day=DAY, cost=LIMIT)

    # Assert
    assert db.used[(1, DAY)] == 0


@pytest.mark.anyio
async def test_another_users_thread_is_not_claimed() -> None:
    """A thread belongs to its first claimer, so the endpoint's 403 path stays
    reachable under load."""
    # Arrange
    db = InMemoryWebDb()
    await db.claim_thread(POOL, thread_id="t", user_id=1, title="first")

    # Act
    claimed = await db.claim_thread(POOL, thread_id="t", user_id=2, title="second")

    # Assert
    assert claimed is False


def test_leaving_the_fake_backend_restores_the_real_graph() -> None:
    """The fakes patch module globals; a test or a run that leaked them would
    send every later caller to the fake models."""
    # Arrange
    real_graph = api.graph
    with fake_backend(LatencyProfile()):
        pass

    # Act
    restored = api.graph

    # Assert
    assert restored is real_graph
