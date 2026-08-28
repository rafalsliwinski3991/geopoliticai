"""Database module for prompt logging."""

from __future__ import annotations

from typing import Any, cast

import asyncpg  # type: ignore[import-untyped]

_pool: Any | None = None


async def init_pool(dsn: str) -> None:
    """Initialize the asyncpg connection pool and ensure the table exists."""
    global _pool
    _pool = await asyncpg.create_pool(dsn)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_logs (
                id        SERIAL PRIMARY KEY,
                datetime  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                prompt    TEXT        NOT NULL,
                ip        VARCHAR(45),
                output    TEXT
            )
            """
        )
        # Existing deployments predate the output column and carry a location
        # column the app no longer writes.
        await conn.execute(
            "ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS output TEXT"
        )
        await conn.execute("ALTER TABLE prompt_logs DROP COLUMN IF EXISTS location")


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def log_prompt(prompt: str, ip: str) -> int | None:
    """Insert a prompt log row and return its ID; returns None if DB unavailable."""
    if _pool is None:
        return None
    try:
        async with _pool.acquire() as conn:
            row_id = await conn.fetchval(
                """
                INSERT INTO prompt_logs (prompt, ip)
                VALUES ($1, $2)
                RETURNING id
                """,
                prompt,
                ip,
            )
            return cast(int, row_id)
    except Exception:
        return None


async def log_output(log_id: int, output: str) -> None:
    """Update a prompt log row with the pipeline output."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE prompt_logs SET output = $1 WHERE id = $2",
                output,
                log_id,
            )
    except Exception:
        pass
