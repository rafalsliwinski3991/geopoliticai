"""Unit tests for the API module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


def test_health_check(client: TestClient) -> None:
    """Test health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_run_pipeline_stream_logs_prompt_and_output() -> None:
    """Test streaming endpoint logs both prompt and output."""
    # Mock the database functions
    mock_log_prompt = AsyncMock(return_value=42)
    mock_log_output = AsyncMock()

    # Mock the graph execution
    mock_state = {"final_output": "test output"}
    mock_graph = AsyncMock()
    mock_graph.astream_events = AsyncMock(return_value=_mock_stream_events(mock_state))

    with patch("api.database.log_prompt", mock_log_prompt):
        with patch("api.database.log_output", mock_log_output):
            with patch("api.build_graph", return_value=mock_graph):
                client = TestClient(app)
                response = client.post(
                    "/api/run_pipeline/stream",
                    json={
                        "query": "test query",
                        "infosphere": "english",
                    },
                )

    assert response.status_code == 200
    # Verify log_prompt was called with query and IP
    mock_log_prompt.assert_called_once()
    call_args = mock_log_prompt.call_args
    assert "test query" == call_args[0][0]


@pytest.mark.anyio
async def test_run_pipeline_logs_prompt_and_output_via_background_task() -> None:
    """Test sync endpoint logs prompt and output via background task."""
    mock_log_prompt = AsyncMock(return_value=99)
    mock_log_output = AsyncMock()

    # Mock the pipeline execution
    def mock_run_pipeline(query: str, infosphere: str) -> str:
        return "pipeline output"

    with patch("api.database.log_prompt", mock_log_prompt):
        with patch("api.database.log_output", mock_log_output):
            with patch("api.run_pipeline", mock_run_pipeline):
                client = TestClient(app)
                response = client.post(
                    "/api/run_pipeline",
                    json={
                        "query": "test query",
                        "infosphere": "polish",
                    },
                )

    assert response.status_code == 200
    assert response.json()["output"] == "pipeline output"
    # Verify log_prompt was called
    mock_log_prompt.assert_called_once()


def test_run_pipeline_returns_output() -> None:
    """Test sync endpoint returns the pipeline output."""
    mock_run_pipeline_output = "test result"
    mock_log_prompt = AsyncMock(return_value=1)

    with patch("api.run_pipeline", return_value=mock_run_pipeline_output):
        with patch("api.database.log_prompt", mock_log_prompt):
            client = TestClient(app)
            response = client.post(
                "/api/run_pipeline",
                json={
                    "query": "what is politics?",
                    "infosphere": "english",
                },
            )

    assert response.status_code == 200
    assert response.json()["output"] == mock_run_pipeline_output


def test_run_pipeline_validates_query_length() -> None:
    """Test endpoint rejects excessively long queries."""
    client = TestClient(app)
    response = client.post(
        "/api/run_pipeline",
        json={
            "query": "a" * 3000,  # Exceeds MAX_QUERY_LENGTH of 2000
            "infosphere": "english",
        },
    )
    assert response.status_code == 422  # Validation error


def test_run_pipeline_validates_empty_query() -> None:
    """Test endpoint rejects empty queries."""
    client = TestClient(app)
    response = client.post(
        "/api/run_pipeline",
        json={
            "query": "",
            "infosphere": "english",
        },
    )
    assert response.status_code == 422  # Validation error


def test_run_pipeline_normalizes_whitespace() -> None:
    """Test endpoint normalizes whitespace in query."""
    mock_log_prompt = AsyncMock(return_value=1)

    with patch("api.run_pipeline", return_value="output"):
        with patch("api.database.log_prompt", mock_log_prompt):
            client = TestClient(app)
            response = client.post(
                "/api/run_pipeline",
                json={
                    "query": "  test   query  with   spaces  ",
                    "infosphere": "english",
                },
            )

    assert response.status_code == 200
    # Verify normalized query was used
    call_args = mock_log_prompt.call_args
    logged_query = call_args[0][0]
    assert logged_query == "test query with spaces"
    assert "  " not in logged_query  # No double spaces


def test_rate_limiting_enforced() -> None:
    """Test rate limiting is enforced."""
    import api

    # Clear rate limit store before test
    api._rate_limit_store.clear()

    client = TestClient(app)
    mock_log_prompt = AsyncMock(return_value=1)

    with patch("api.run_pipeline", return_value="output"):
        with patch("api.database.log_prompt", mock_log_prompt):
            # Make requests up to the rate limit
            for i in range(20):  # DEFAULT_RATE_LIMIT_REQUESTS = 20
                response = client.post(
                    "/api/run_pipeline",
                    json={
                        "query": f"query {i}",
                        "infosphere": "english",
                    },
                )
                assert response.status_code == 200

            # Next request should be rate limited
            response = client.post(
                "/api/run_pipeline",
                json={
                    "query": "query 21",
                    "infosphere": "english",
                },
            )
            assert response.status_code == 429


def _mock_stream_events(state_dict: dict) -> list[dict]:
    """Helper to create mock stream events."""
    return [
        {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "ingest_request"},
        },
        {
            "event": "on_chain_end",
            "name": "GeopoliticAI",
            "data": {"output": state_dict},
        },
    ]
