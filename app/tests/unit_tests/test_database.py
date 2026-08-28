"""Unit tests for the database module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import database


@pytest.mark.anyio
async def test_log_prompt_returns_none_when_pool_unavailable() -> None:
    """Test log_prompt returns None if connection pool is unavailable."""
    database._pool = None
    result = await database.log_prompt("test query", "192.168.1.1")
    assert result is None


@pytest.mark.anyio
async def test_log_prompt_returns_row_id_on_success() -> None:
    """Test log_prompt returns the inserted row ID."""
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=42)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    with patch("database._pool", mock_pool):
        result = await database.log_prompt("test query", "192.168.1.1")

    assert result == 42
    mock_conn.fetchval.assert_called_once()
    # Verify the INSERT query
    call_args = mock_conn.fetchval.call_args
    assert "INSERT INTO prompt_logs" in call_args[0][0]
    assert "RETURNING id" in call_args[0][0]


@pytest.mark.anyio
async def test_log_prompt_handles_exception_gracefully() -> None:
    """Test log_prompt returns None if database operation fails."""
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(side_effect=Exception("DB error"))

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    with patch("database._pool", mock_pool):
        result = await database.log_prompt("test query", "192.168.1.1")

    assert result is None


@pytest.mark.anyio
async def test_log_output_returns_none_when_pool_unavailable() -> None:
    """Test log_output returns None if connection pool is unavailable."""
    database._pool = None
    await database.log_output(1, "test output")


@pytest.mark.anyio
async def test_log_output_updates_row_on_success() -> None:
    """Test log_output updates the database row."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    with patch("database._pool", mock_pool):
        await database.log_output(42, "test output")

    mock_conn.execute.assert_called_once()
    # Verify the UPDATE query
    call_args = mock_conn.execute.call_args
    assert "UPDATE prompt_logs SET output" in call_args[0][0]
    assert "WHERE id" in call_args[0][0]
    # Verify parameters
    assert call_args[0][1] == "test output"
    assert call_args[0][2] == 42


@pytest.mark.anyio
async def test_log_output_handles_exception_gracefully() -> None:
    """Test log_output silently fails if database operation fails."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB error"))

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )

    with patch("database._pool", mock_pool):
        # Should not raise exception
        await database.log_output(1, "test output")


@pytest.mark.anyio
async def test_init_pool_drops_location_column() -> None:
    """Test init_pool drops the retired location column on existing tables."""
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )

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
