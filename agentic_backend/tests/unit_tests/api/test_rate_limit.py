from typing import Any, AsyncIterator, cast
from unittest.mock import patch

import httpx
import pytest

from api import auth, rate_limit, stream
from shared.frames import TokenFrame
from unit_tests.api.conftest import (
    _client_with_token,
    _mint_token,
)


@pytest.mark.anyio
async def test_rate_limit_keys_on_the_authenticated_user(
    client: httpx.AsyncClient,
) -> None:
    """A signed-in caller cannot rotate X-Forwarded-For to get a fresh bucket (Q17)."""

    # Arrange
    # Arrange
    async def turn(
        graph: Any, graph_input: Any, thread_id: str
    ) -> AsyncIterator[stream.StreamEvent]:
        yield TokenFrame(content="answer")

    # Act
    with patch("api.stream._astream_answer", turn):
        for index in range(rate_limit.RATE_LIMIT_REQUESTS):
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
        other_identity = _client_with_token(_mint_token(user_id=2))
        allowed = await other_identity.post(
            "/api/run_pipeline/stream",
            json={"query": "different client", "thread_id": "t-1"},
        )
    # Assert
    assert blocked.status_code == 429
    assert allowed.status_code == 200


def test_resolve_client_id_falls_back_to_the_rightmost_forwarded() -> None:
    """The unauthenticated fallback keeps the right-most-entry rule."""

    # Arrange
    # Arrange
    stub = cast(
        Any,
        type(
            "R",
            (),
            {"headers": {"x-forwarded-for": "a, b, 203.0.113.5"}, "client": None},
        )(),
    )
    # Act
    resolved_anonymous = rate_limit._resolve_client_id(stub)
    resolved_authenticated = rate_limit._resolve_client_id(
        stub, auth.Identity(user_id=7)
    )
    # Assert
    assert resolved_anonymous == "203.0.113.5"
    assert resolved_authenticated == "user:7"
    assert rate_limit._resolve_client_id(stub, auth.Identity(user_id=7)) == "user:7"


@pytest.mark.anyio
async def test_rate_limiting_enforced(client: httpx.AsyncClient) -> None:
    # Arrange
    async def turn(
        graph: Any, graph_input: Any, thread_id: str
    ) -> AsyncIterator[stream.StreamEvent]:
        # Arrange
        yield TokenFrame(content="output")

    # Act
    with patch("api.stream._astream_answer", turn):
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
    # Assert
    assert response.status_code == 429
