"""Unit tests for the database module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import database


def _mock_pool(mock_conn: MagicMock) -> MagicMock:
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    return mock_pool


@pytest.mark.anyio
async def test_log_run_is_silent_when_pool_unavailable() -> None:
    """Test log_run does nothing if the connection pool is unavailable."""
    database._pool = None
    await database.log_run("test query", "192.168.1.1", "test output")


@pytest.mark.anyio
async def test_log_run_inserts_prompt_ip_and_output() -> None:
    """Test log_run issues one INSERT carrying all three values."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()

    with patch("database._pool", _mock_pool(mock_conn)):
        await database.log_run("test query", "192.168.1.1", "test output")

    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args
    assert "INSERT INTO prompt_logs" in call_args[0][0]
    assert call_args[0][1] == "test query"
    assert call_args[0][2] == "192.168.1.1"
    assert call_args[0][3] == "test output"


@pytest.mark.anyio
async def test_log_run_handles_exception_gracefully() -> None:
    """Test log_run swallows a raising connection."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))

    with patch("database._pool", _mock_pool(mock_conn)):
        # Should not raise exception
        await database.log_run("test query", "192.168.1.1", "test output")


@pytest.mark.anyio
async def test_init_pool_drops_location_column() -> None:
    """Test init_pool drops the retired location column on existing tables."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_pool = _mock_pool(mock_conn)

    try:
        with patch(
            "database.asyncpg.create_pool", new=AsyncMock(return_value=mock_pool)
        ):
            await database.init_pool("postgresql://example")
        statements = [call[0][0] for call in mock_conn.execute.call_args_list]
        assert any(
            "DROP COLUMN IF EXISTS location" in statement for statement in statements
        )
        assert all("location  VARCHAR" not in statement for statement in statements)
    finally:
        # `init_pool` writes the module global; leaving a MagicMock there would
        # be seen by every later test that does not set `_pool` explicitly.
        database._pool = None
