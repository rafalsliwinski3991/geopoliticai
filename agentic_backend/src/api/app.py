"""The FastAPI application: lifespan, checkpointer, store, CORS, and the routers."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.base import TTLConfig
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from agents.orchestrator import (
    build_graph,
)
from agents.orchestrator import graph as _default_graph
from api import routes, stream
from shared.config import (
    init_environment,
    require_env,
)
from shared.tracing import init_tracing

logger = logging.getLogger(__name__)

# Explicit msgpack allow-list (POLI-16): the expert subgraph checkpoints
# `models.Source`; every other custom type is refused rather than rebuilt.
# LangChain messages and primitives are always allowed.
CHECKPOINT_SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("models", "Source")])

# The store holds only the deep forecaster's cached video notes (plan unit 09).
# Every item expires 30 days after it is written, as the privacy page says:
# reads never refresh it, and an expired item is never returned, even before
# the hourly sweep deletes it. The TTL lives here, not in `aput`, because the
# in-memory store the tests use has no TTL support.
STORE_TTL: TTLConfig = {
    "default_ttl": 30 * 24 * 60,
    "refresh_on_read": False,
    "omit_expired": True,
    "sweep_interval_minutes": 60,
}

# Hardcoded the way `LLMSettings` is hardcoded: edited here, never read from
# the environment.
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8082",
    "http://localhost:3001",
]
# The checkpointer names its tables unqualified in both its DDL and its
# queries, so search_path is the only way to put them anywhere but `public`.
# `agentic` first means setup() creates there; `public` second means
# db/web/sql.py still resolves Django's tables. Verified against
# langgraph-checkpoint-postgres 3.1.2, whose package contains no schema support.
POSTGRES_SEARCH_PATH = "agentic,public"
POSTGRES_CONNECTION_KWARGS: dict[str, Any] = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
    # Spaced form: libpq documents `options=-c name=value`. The concatenated
    # `-cname=value` happens to work because the backend arg parser is
    # getopt-based, but that is incidental, and this setting is the single
    # lever the whole schema design rests on.
    "options": f"-c search_path={POSTGRES_SEARCH_PATH}",
}
POSTGRES_POOL_MIN_SIZE = 1
POSTGRES_POOL_MAX_SIZE = 10


async def _require_migrated_checkpointer_schema(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
) -> None:
    """Refuse to start when the checkpointer tables have not been migrated yet.

    This runs BEFORE `setup()`, and the ordering is the entire point.
    `CREATE TABLE IF NOT EXISTS` resolves to the first schema in `search_path`
    and checks existence only THERE — it does not check visibility. So calling
    `setup()` while the tables are still in `public` does not find them: it
    builds a complete second, empty set in `agentic`, every thread's history
    becomes invisible to unqualified reads, and
    `0002_checkpointer_to_agentic` then refuses to move anything because both
    copies exist. Verified by execution against Postgres 16.

    Checking first costs one query and makes that state unreachable. On a fresh
    database neither table exists and this passes.

    The same query also requires `current_schema()` to be `agentic`, which is
    where `setup()`'s unqualified `CREATE TABLE` lands. It is not when the
    `agentic` schema does not exist yet (Postgres skips missing schemas in
    `search_path`) or when the pool's `options` do not reach the connection;
    either way `setup()` would build a fresh set in `public`.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT to_regclass('public.checkpoints') AS stray,"
            " current_schema() AS target"
        )
        row = await cursor.fetchone() or {}
    if row.get("stray") is not None:
        raise RuntimeError(
            "public.checkpoints still exists, so the checkpointer schema has "
            "not been migrated. Run `make migrate-agentic` BEFORE starting "
            "this service. Starting first creates an empty second set of "
            "tables in `agentic` and hides the real history."
        )
    if row.get("target") != "agentic":
        raise RuntimeError(
            f"setup() would create the checkpointer tables in {row.get('target')!r}, "
            "not `agentic`: either the schema does not exist yet (run "
            "`make migrate-agentic`) or the pool's search_path is not reaching "
            "the connection."
        )


async def _assert_agentic_schema(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
) -> None:
    """Confirm both `setup()` calls put their tables where `search_path` should have.

    Cheap second assertion. If this fires, the pool's `options` are not
    reaching the connection.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT to_regclass('agentic.checkpoints') AS checkpoints,"
            " to_regclass('agentic.store') AS store"
        )
        row = await cursor.fetchone() or {}
    for table in ("checkpoints", "store"):
        if row.get(table) is None:
            raise RuntimeError(
                f"agentic.{table} does not exist after setup(): the pool's "
                "search_path is not reaching the connection."
            )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize application resources; require a database for threads."""
    init_environment()
    init_tracing()
    require_env()
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise ValueError(
            "DATABASE_URL is required: conversation threads are stored in Postgres."
        )
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        conninfo=db_url,
        min_size=POSTGRES_POOL_MIN_SIZE,
        max_size=POSTGRES_POOL_MAX_SIZE,
        kwargs=POSTGRES_CONNECTION_KWARGS,
        open=False,
    )
    await pool.open()
    store: AsyncPostgresStore | None = None
    try:
        checkpointer = AsyncPostgresSaver(pool, serde=CHECKPOINT_SERDE)
        await _require_migrated_checkpointer_schema(pool)
        await checkpointer.setup()
        # Built here, not at import: it captures the running loop. Same pool,
        # so the guard above also decides where its tables land.
        store = AsyncPostgresStore(pool, ttl=STORE_TTL)
        await store.setup()
        await _assert_agentic_schema(pool)
        await store.start_ttl_sweeper()
        _app.state.graph = build_graph(checkpointer=checkpointer, store=store)
        # The thread/quota endpoints and the identity dependencies reach the
        # pool the checkpointer already shares; no second pool is opened.
        _app.state.pool = pool
        yield
    finally:
        _app.state.graph = _default_graph
        # A sweeper stuck on the database must not skip closing the pool
        # (review thread, #151): bounded wait, and the pool closes in its own
        # finally, whatever the sweeper did.
        if store is not None:
            try:
                async with asyncio.timeout(5.0):
                    await store.stop_ttl_sweeper()
            except TimeoutError:
                logger.warning(
                    "the TTL sweeper did not stop within 5 s; closing the pool anyway"
                )
        try:
            await pool.close()
        except RuntimeError:
            logger.warning("the pool was already closed", exc_info=True)


app = FastAPI(title="GeopoliticAI API", version="1.0.0", lifespan=lifespan)
# A fresh app serves the checkpointer-less graph until `lifespan` swaps it in;
# tests drive the app through ASGITransport, which never runs `lifespan`.
app.state.graph = _default_graph
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(routes.router)
app.include_router(stream.router)
