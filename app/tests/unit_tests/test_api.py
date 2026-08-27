import json
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import api
from llm import LLMInvocationError
from models import NoSourcesError, SearchUnavailableError


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
    with (
        patch("api.run_pipeline", new=AsyncMock(return_value="answer")),
        patch("api.database.log_prompt", new=AsyncMock(return_value=None)),
    ):
        response = await client.post(
            "/api/run_pipeline", json={"query": "x", "info" + "sphere": "legacy"}
        )
    assert response.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NoSourcesError("none"), 422),
        (SearchUnavailableError("down"), 503),
        (LLMInvocationError("bad"), 502),
    ],
)
async def test_sync_maps_pipeline_errors(
    client: httpx.AsyncClient, error: Exception, status: int
) -> None:
    async def boom(query: str, **kwargs: object) -> None:
        raise error

    with (
        patch("api.run_pipeline", boom),
        patch("api.database.log_prompt", new=AsyncMock(return_value=None)),
    ):
        response = await client.post("/api/run_pipeline", json={"query": "x"})
    assert response.status_code == status
    assert response.json()["detail"] == str(error)


@pytest.mark.anyio
async def test_stream_progress_tokens_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str, **kwargs: object) -> AsyncIterator[tuple[str, str]]:
        yield ("progress", "search_and_fetch")
        yield ("token", "Hello ")
        yield ("token", "world.")

    log_prompt = AsyncMock(return_value=None)
    with (
        patch("api.astream_pipeline", stream),
        patch("api.database.log_prompt", log_prompt),
    ):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    assert [event["type"] for event in events] == [
        "progress",
        "token",
        "token",
        "result",
    ]
    assert events[0]["label"] == "Searching and reading sources..."
    assert events[-1]["output"] == "Hello world."
    log_prompt.assert_awaited_once_with("x", "127.0.0.1")


@pytest.mark.anyio
async def test_stream_logs_output_before_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str, **kwargs: object) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    log_output = AsyncMock()
    order: list[str] = []

    async def record_output(log_id: int, output: str) -> None:
        order.append("log")
        await log_output(log_id, output)

    async def record_stream(
        query: str, **kwargs: object
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    with (
        patch("api.astream_pipeline", record_stream),
        patch("api.database.log_prompt", new=AsyncMock(return_value=42)),
        patch("api.database.log_output", record_output),
    ):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    order.append(events[-1]["type"])
    assert order == ["log", "result"]
    log_output.assert_awaited_once_with(42, "answer")


@pytest.mark.anyio
async def test_stream_error_has_no_result(client: httpx.AsyncClient) -> None:
    async def stream(query: str, **kwargs: object) -> AsyncIterator[tuple[str, str]]:
        raise NoSourcesError("nothing usable")
        yield ("token", "never")

    with (
        patch("api.astream_pipeline", stream),
        patch("api.database.log_prompt", new=AsyncMock(return_value=None)),
    ):
        response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    events = _events(response.text)
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["message"] == "nothing usable"


@pytest.mark.anyio
async def test_sync_logs_prompt_and_output(client: httpx.AsyncClient) -> None:
    log_prompt = AsyncMock(return_value=99)
    log_output = AsyncMock()
    with (
        patch("api.run_pipeline", new=AsyncMock(return_value="output")),
        patch("api.database.log_prompt", log_prompt),
        patch("api.database.log_output", log_output),
    ):
        response = await client.post("/api/run_pipeline", json={"query": "x"})
    assert response.status_code == 200
    assert response.json()["output"] == "output"
    log_prompt.assert_awaited_once_with("x", "127.0.0.1")
    log_output.assert_awaited_once_with(99, "output")


@pytest.mark.anyio
async def test_query_validation(client: httpx.AsyncClient) -> None:
    assert (
        await client.post("/api/run_pipeline", json={"query": ""})
    ).status_code == 422
    assert (
        await client.post("/api/run_pipeline", json={"query": "x" * 3000})
    ).status_code == 422


@pytest.mark.anyio
async def test_rate_limiting_enforced(client: httpx.AsyncClient) -> None:
    with (
        patch("api.run_pipeline", new=AsyncMock(return_value="output")),
        patch("api.database.log_prompt", new=AsyncMock(return_value=None)),
    ):
        for index in range(20):
            response = await client.post(
                "/api/run_pipeline", json={"query": f"query {index}"}
            )
            assert response.status_code == 200
        response = await client.post("/api/run_pipeline", json={"query": "query 21"})
    assert response.status_code == 429
