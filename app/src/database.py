"""Database module for prompt logging."""

from __future__ import annotations

from typing import Any

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
        # Existing deployments predate the output column; add it if missing. The
        # legacy `location` column (when present) is left alone: it is harmless
        # because the INSERT below names only the columns it writes.
        await conn.execute(
            "ALTER TABLE prompt_logs ADD COLUMN IF NOT EXISTS output TEXT"
        )


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def log_run(prompt: str, ip: str, output: str) -> None:
    """Record one completed run; silent when the database is unavailable."""
    if _pool is None:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO prompt_logs (prompt, ip, output)
                VALUES ($1, $2, $3)
                """,
                prompt,
                ip,
                output,
            )
    except Exception:
        pass
