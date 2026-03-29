"""Database module for prompt logging."""

from __future__ import annotations

from typing import Optional

import asyncpg
import httpx

_pool: Optional[asyncpg.Pool] = None


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
                location  VARCHAR(255)
            )
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


async def log_prompt(prompt: str, ip: str) -> None:
    """Insert a prompt log row; silently skips if DB is unavailable."""
    if _pool is None:
        return
    location = await _resolve_location(ip)
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO prompt_logs (prompt, ip, location) VALUES ($1, $2, $3)",
                prompt,
                ip,
                location,
            )
    except Exception:
        pass
