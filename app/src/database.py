"""Database module for prompt logging."""

from __future__ import annotations

import logging
from typing import Any, cast

import asyncpg  # type: ignore[import-untyped]
import httpx

logger = logging.getLogger(__name__)
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
                location  VARCHAR(255),
                output    TEXT
            )
            """
        )
        # Add output column to existing tables
        await conn.execute(
            """
            ALTER TABLE prompt_logs
            ADD COLUMN IF NOT EXISTS output TEXT
            """
        )


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _resolve_location(ip: str) -> str:
    if ip in ("unknown", "127.0.0.1", "::1"):
        return "local"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "city,country"},
            )
            data = resp.json()
        parts = [data.get("city", ""), data.get("country", "")]
        return ", ".join(p for p in parts if p) or "unknown"
    except Exception:
        return "unknown"


async def log_prompt(prompt: str, ip: str) -> int | None:
    """Insert a prompt log row and return its ID; returns None if DB unavailable."""
    if _pool is None:
        return None
    location = await _resolve_location(ip)
    try:
        async with _pool.acquire() as conn:
            row_id = await conn.fetchval(
                """
                INSERT INTO prompt_logs (prompt, ip, location)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                prompt,
                ip,
                location,
            )
            return cast(int, row_id)
    except Exception:
        logger.warning("Failed to write prompt log row.", exc_info=True)
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
        logger.warning("Failed to update prompt log row %s.", log_id, exc_info=True)
