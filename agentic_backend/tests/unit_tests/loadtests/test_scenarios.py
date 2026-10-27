import os

import httpx
import pytest

import api
from loadtests.fakes import LatencyProfile, fake_backend
from loadtests.scenarios import USER_ROUND, run_load, stream_turn

USERS = 6
ROUNDS = 2


def _asgi_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    )


def _client_answering(response: httpx.Response) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: response),
        base_url="http://test",
    )


@pytest.mark.anyio
async def test_every_request_of_a_concurrent_run_succeeds() -> None:
    """Concurrent users on separate threads must not see each other's state:
    every chat, research, list, and history request of every user succeeds."""
    # Arrange
    with fake_backend(LatencyProfile()):
        async with _asgi_client() as client:
            # Act
            result = await run_load(
                client,
                users=USERS,
                rounds=ROUNDS,
                ramp_up=0.0,
                signing_key=os.environ["JWT_SIGNING_KEY"],
            )

    # Assert
    assert len(result.samples) == USERS * ROUNDS * len(USER_ROUND)
    assert [sample for sample in result.samples if not sample.ok] == []


@pytest.mark.anyio
async def test_each_research_turn_charges_its_own_user_one_unit() -> None:
    """The run drives the real `quota.charge_turn`: each user pays one unit per
    research turn and nothing for chat, however the turns interleave."""
    # Arrange
    with fake_backend(LatencyProfile()) as db:
        async with _asgi_client() as client:
            # Act
            await run_load(
                client,
                users=USERS,
                rounds=ROUNDS,
                ramp_up=0.0,
                signing_key=os.environ["JWT_SIGNING_KEY"],
            )

    # Assert
    assert sorted(db.used.values()) == [ROUNDS] * USERS
    assert sum(db.site_used.values()) == USERS * ROUNDS


@pytest.mark.anyio
async def test_a_turn_ending_in_an_error_frame_is_a_failure() -> None:
    """The endpoint answers 200 and reports a failed turn inside the stream, so
    the status code alone would count every refused turn as a success."""
    # Arrange
    body = 'data: {"type": "error", "status": 429, "message": "limit"}\n\n'
    response = httpx.Response(200, text=body)

    # Act
    async with _client_answering(response) as client:
        sample = await stream_turn(
            client, "research", thread_id="t", query="q", token="x"
        )

    # Assert
    assert (sample.ok, sample.error) == (False, "error frame 429")


@pytest.mark.anyio
async def test_a_stream_cut_before_its_result_is_a_failure() -> None:
    """A stream that stops after its tokens never told the user the turn ended."""
    # Arrange
    body = 'data: {"type": "token", "content": "Hel"}\n\n'
    response = httpx.Response(200, text=body)

    # Act
    async with _client_answering(response) as client:
        sample = await stream_turn(client, "chat", thread_id="t", query="q", token="x")

    # Assert
    assert (sample.ok, sample.error) == (False, "stream ended without a result")


@pytest.mark.anyio
async def test_a_refused_request_is_a_failure_with_its_status() -> None:
    """A pre-stream refusal (401, 403, 429) is recorded with its status, so the
    report says which limit the run hit."""
    # Arrange
    response = httpx.Response(429, json={"detail": "Rate limit exceeded"})

    # Act
    async with _client_answering(response) as client:
        sample = await stream_turn(client, "chat", thread_id="t", query="q", token="x")

    # Assert
    assert (sample.ok, sample.error) == (False, "http 429")
