import json
from typing import Any, AsyncIterator, Literal, cast
from unittest.mock import patch

import httpx
import pytest

import api
from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    SearchUnavailableError,
)


@pytest.fixture
def client() -> httpx.AsyncClient:
    api._rate_limit_store.clear()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    )


def _events(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.anyio
async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_unknown_legacy_field_is_ignored(client: httpx.AsyncClient) -> None:
    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        yield ("route", "other")
        yield ("token", "answer")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x", "thread_id": "t-1", "info" + "sphere": "legacy"},
        )
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"


@pytest.mark.anyio
async def test_sync_route_is_gone(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/run_pipeline", json={"query": "x", "thread_id": "t-1"}
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_stream_progress_tokens_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        yield ("route", "other")
        yield ("token", "Hello ")
        yield ("token", "world.")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert [event["type"] for event in events] == [
        "progress",
        "progress",
        "token",
        "token",
        "result",
    ]
    assert [event["label"] for event in events if event["type"] == "progress"] == [
        "Thinking...",
        "Writing the answer...",
    ]
    assert all(
        event.get("label") != "Searching and reading sources..." for event in events
    )
    assert events[-1]["output"] == "Hello world."


@pytest.mark.anyio
async def test_expert_route_emits_the_search_frame(client: httpx.AsyncClient) -> None:
    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        yield ("route", "geopolitical")
        yield ("token", "Hello world.")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    progress = [
        event["label"]
        for event in _events(response.text)
        if event["type"] == "progress"
    ]
    assert progress == [
        "Thinking...",
        "Searching and reading sources...",
        "Writing the answer...",
    ]


@pytest.mark.anyio
async def test_stream_caps_answer_size(client: httpx.AsyncClient) -> None:
    fully_consumed = False

    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        nonlocal fully_consumed
        yield ("route", "other")
        yield ("token", "x" * (api.MAX_ANSWER_CHARS + 1000))
        yield ("token", "ignored after the cap")
        fully_consumed = True

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert len(events[-1]["output"]) == api.MAX_ANSWER_CHARS
    assert fully_consumed


@pytest.mark.anyio
async def test_rate_limit_keys_on_rightmost_forwarded(
    client: httpx.AsyncClient,
) -> None:
    """A caller cannot rotate the left-hand forwarded entry to get a fresh bucket."""

    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    with patch("api._astream_answer", stream):
        for index in range(api.RATE_LIMIT_REQUESTS):
            response = await client.post(
                "/api/run_pipeline/stream",
                json={"query": f"q{index}", "thread_id": "t-1"},
                headers={"x-forwarded-for": f"spoofed-{index}, 203.0.113.5"},
            )
            assert response.status_code == 200
        blocked = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "one more", "thread_id": "t-1"},
            headers={"x-forwarded-for": "another-spoof, 203.0.113.5"},
        )
        allowed = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "different client", "thread_id": "t-1"},
            headers={"x-forwarded-for": "spoofed, 203.0.113.6"},
        )
    assert blocked.status_code == 429
    assert allowed.status_code == 200


@pytest.mark.anyio
async def test_stream_error_has_no_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        raise NoSourcesError("nothing usable")
        yield ("token", "never")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    # The thinking progress frame precedes the graph, so it survives a failure.
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["message"] == "nothing usable"


@pytest.mark.anyio
async def test_thread_id_is_required(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_thread_id_shape_is_validated(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "../../etc"}
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_query_validation(client: httpx.AsyncClient) -> None:
    assert (
        await client.post(
            "/api/run_pipeline/stream", json={"query": "", "thread_id": "t-1"}
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x" * 3000, "thread_id": "t-1"},
        )
    ).status_code == 422


@pytest.mark.anyio
async def test_rate_limiting_enforced(client: httpx.AsyncClient) -> None:
    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "output")

    with patch("api._astream_answer", stream):
        for index in range(20):
            response = await client.post(
                "/api/run_pipeline/stream",
                json={"query": f"query {index}", "thread_id": "t-1"},
            )
            assert response.status_code == 200
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "query 21", "thread_id": "t-1"},
        )
    assert response.status_code == 429


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NoSourcesError("none"), 422),
        (SearchUnavailableError("down"), 503),
        (LLMInvocationError("bad"), 502),
    ],
)
async def test_stream_reports_error_status_per_type(
    client: httpx.AsyncClient, error: PipelineError, status: int
) -> None:
    async def stream(query: str, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        raise error
        yield ("token", "never")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["status"] == status
    assert events[-1]["message"] == str(error)


@pytest.mark.anyio
async def test_lifespan_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "init_environment", lambda: None)
    monkeypatch.setattr(api, "init_tracing", lambda: None)
    monkeypatch.setattr(api, "require_env", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with patch("api.AsyncConnectionPool") as pool:
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            async with api.lifespan(api.app):
                pass
        pool.assert_not_called()


@pytest.mark.parametrize(
    ("destination", "expected"),
    [("geopolitical", "Hello world."), ("other", "Hello world.")],
)
@pytest.mark.anyio
async def test_astream_answer_streams_the_answer_of_either_branch(
    monkeypatch: pytest.MonkeyPatch, destination: str, expected: str
) -> None:
    """The one test that actually executes `_astream_answer`.

    Covers `subgraphs=True`, the three-tuple unpacking, the route event, the
    `langgraph_node` filter across both answer nodes, the `AIMessage`
    narrowing, and `message.text()` together; every other test here patches it
    out. The geopolitical case is the regression guard for nested-subgraph
    streaming: without `subgraphs=True` it yields nothing at all.
    """
    import importlib

    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from agents.orchestrator.state import RouteDecision
    from models import Candidate, Source

    search_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
    classify_module = importlib.import_module("agents.orchestrator.nodes.classify")
    llm_module = importlib.import_module("llm")
    graph_module = importlib.import_module("agents.orchestrator.graph")

    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("title", "https://reuters.com/x", "reuters.com")]

    async def sources(items: list[Candidate], policy: Any) -> list[Source]:
        return [Source("title", "https://reuters.com/x", "body")]

    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        route = cast(Literal["geopolitical", "other"], destination)
        return RouteDecision(destination=route, standalone_query="rewritten")

    monkeypatch.setattr(search_module, "search_allowlisted", candidates)
    monkeypatch.setattr(search_module, "fetch_sources", sources)
    monkeypatch.setattr(classify_module, "ainvoke_structured", decide)
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=["Hello world."]),
    )
    monkeypatch.setattr(api, "graph", graph_module.build_graph())

    events = [event async for event in api._astream_answer("question", "t-1")]
    assert ("route", destination) in events
    assert events[0] == ("route", destination)
    assert "".join(text for kind, text in events if kind == "token") == expected
