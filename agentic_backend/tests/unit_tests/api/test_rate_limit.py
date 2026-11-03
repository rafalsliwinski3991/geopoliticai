from typing import Any, AsyncIterator, cast
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

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
        graph: Any, graph_input: Any, thread_id: str, context: Any = None
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
        graph: Any, graph_input: Any, thread_id: str, context: Any = None
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


UPLOAD_USER = 7
OTHER_UPLOAD_USER = 8
UPLOAD_CLOCK_START = 1000.0


def _identity(user_id: int) -> auth.Identity:
    return auth.Identity(user_id=user_id)


def test_the_eleventh_upload_in_an_hour_is_refused() -> None:
    """Embedding costs money, so a user gets ten uploads an hour and no more."""
    # Arrange
    rate_limit._upload_store.clear()
    for _ in range(10):
        rate_limit.enforce_upload_limit(_identity(UPLOAD_USER))

    # Act + Assert
    with pytest.raises(HTTPException) as refused:
        rate_limit.enforce_upload_limit(_identity(UPLOAD_USER))
    assert refused.value.status_code == 429


def test_an_upload_made_an_hour_ago_no_longer_counts() -> None:
    """The window slides: a user who waited an hour gets their uploads back."""
    # Arrange
    rate_limit._upload_store.clear()
    with patch("api.rate_limit.time.monotonic", return_value=UPLOAD_CLOCK_START):
        for _ in range(10):
            rate_limit.enforce_upload_limit(_identity(UPLOAD_USER))
    after_the_window = UPLOAD_CLOCK_START + rate_limit.UPLOAD_LIMIT_WINDOW_SECONDS + 1

    # Act
    with patch("api.rate_limit.time.monotonic", return_value=after_the_window):
        rate_limit.enforce_upload_limit(_identity(UPLOAD_USER))

    # Assert
    assert len(rate_limit._upload_store[UPLOAD_USER]) == 1


def test_upload_limits_are_per_user() -> None:
    """One user's uploads must not use up another's."""
    # Arrange
    rate_limit._upload_store.clear()
    for _ in range(10):
        rate_limit.enforce_upload_limit(_identity(UPLOAD_USER))

    # Act
    rate_limit.enforce_upload_limit(_identity(OTHER_UPLOAD_USER))

    # Assert
    assert len(rate_limit._upload_store[OTHER_UPLOAD_USER]) == 1
