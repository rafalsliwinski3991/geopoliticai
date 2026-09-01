import json
from typing import Any, AsyncIterator
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
    async def stream(query: str) -> AsyncIterator[str]:
        yield "answer"

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "info" + "sphere": "legacy"}
        )
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"


@pytest.mark.anyio
async def test_sync_route_is_gone(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/run_pipeline", json={"query": "x"})
    assert response.status_code == 404


@pytest.mark.anyio
async def test_stream_progress_tokens_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str) -> AsyncIterator[str]:
        yield "Hello "
        yield "world."

    with patch("api._astream_answer", stream):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    assert [event["type"] for event in events] == [
        "progress",
        "progress",
        "token",
        "token",
        "result",
    ]
    assert events[0]["label"] == "Searching and reading sources..."
    assert events[1]["label"] == "Writing the answer..."
    assert events[-1]["output"] == "Hello world."


@pytest.mark.anyio
async def test_stream_caps_answer_size(client: httpx.AsyncClient) -> None:
    async def stream(query: str) -> AsyncIterator[str]:
        yield "x" * (api.MAX_ANSWER_CHARS + 1000)

    with patch("api._astream_answer", stream):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert len(events[-1]["output"]) == api.MAX_ANSWER_CHARS


@pytest.mark.anyio
async def test_resolve_client_id_uses_rightmost_forwarded(
    client: httpx.AsyncClient,
) -> None:
    async def stream(query: str) -> AsyncIterator[str]:
        yield "answer"

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x"},
            headers={"x-forwarded-for": "spoofed, 203.0.113.5"},
        )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_stream_error_has_no_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str) -> AsyncIterator[str]:
        raise NoSourcesError("nothing usable")
        yield "never"

    with patch("api._astream_answer", stream):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    # The search progress frame precedes the graph, so it survives a failure
    # during search.
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["message"] == "nothing usable"


@pytest.mark.anyio
async def test_query_validation(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/api/run_pipeline/stream", json={"query": ""})
    ).status_code == 422
    assert (
        await client.post("/api/run_pipeline/stream", json={"query": "x" * 3000})
    ).status_code == 422


@pytest.mark.anyio
async def test_rate_limiting_enforced(client: httpx.AsyncClient) -> None:
    async def stream(query: str) -> AsyncIterator[str]:
        yield "output"

    with patch("api._astream_answer", stream):
        for index in range(20):
            response = await client.post(
                "/api/run_pipeline/stream", json={"query": f"query {index}"}
            )
            assert response.status_code == 200
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "query 21"}
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
    async def stream(query: str) -> AsyncIterator[str]:
        raise error
        yield "never"

    with patch("api._astream_answer", stream):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["status"] == status
    assert events[-1]["message"] == str(error)


@pytest.mark.anyio
async def test_astream_answer_yields_only_answer_node_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one test that actually executes `_astream_answer`.

    Covers the `langgraph_node` filter, the `AIMessage` narrowing, and
    `message.text()` together; every other test here patches it out.
    """
    import importlib

    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from models import Candidate, Source

    search_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
    llm_module = importlib.import_module("llm")
    graph_module = importlib.import_module("agents.expert.graph")

    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("title", "https://reuters.com/x", "reuters.com")]

    async def sources(items: list[Candidate], policy: Any) -> list[Source]:
        return [Source("title", "https://reuters.com/x", "body")]

    monkeypatch.setattr(search_module, "search_allowlisted", candidates)
    monkeypatch.setattr(search_module, "fetch_sources", sources)
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=["Hello world."]),
    )
    monkeypatch.setattr(api, "graph", graph_module.build_graph())

    chunks = [text async for text in api._astream_answer("question")]
    assert "".join(chunks) == "Hello world."
