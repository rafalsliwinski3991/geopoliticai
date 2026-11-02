"""Raw-psycopg access to `agentic.document_chunks`, the uploaded documents' vectors.

Alembic (`0004_document_chunks`) owns the table. `chat_threads` is Django's table,
read here only to keep orphaned chunks out of a user's document count. Thread ids
are chosen by the client and chunks can outlive their thread, so every read and
the user's own delete is scoped by `user_id` as well as `thread_id`.
"""

from __future__ import annotations

from collections.abc import Sequence

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

# Held until the transaction ends, so two replaces of one thread run one after the other.
LOCK_THREAD = "SELECT pg_advisory_xact_lock(hashtext(%(thread_id)s))"
# Replacing a thread's document clears every row under that id, whoever wrote it:
# an old owner's leftovers under a reused id go too.
DELETE_THREAD_CHUNKS = "DELETE FROM document_chunks WHERE thread_id = %(thread_id)s"
DELETE_USER_CHUNKS = """
DELETE FROM document_chunks
WHERE thread_id = %(thread_id)s AND user_id = %(user_id)s
"""
INSERT_CHUNK = """
INSERT INTO document_chunks
    (thread_id, user_id, filename, chunk_index, content, embedding)
VALUES
    (%(thread_id)s, %(user_id)s, %(filename)s, %(chunk_index)s, %(content)s,
     %(embedding)s::vector)
"""
SELECT_NEAREST_CHUNKS = """
SELECT filename, chunk_index, content
FROM document_chunks
WHERE thread_id = %(thread_id)s AND user_id = %(user_id)s
ORDER BY embedding <=> %(embedding)s::vector
LIMIT %(limit)s
"""
SELECT_DOCUMENT_NAME = """
SELECT filename FROM document_chunks
WHERE thread_id = %(thread_id)s AND user_id = %(user_id)s
LIMIT 1
"""
COUNT_LIVE_DOCUMENTS = """
SELECT count(DISTINCT c.thread_id) AS documents
FROM document_chunks c
JOIN chat_threads t ON t.id = c.thread_id
WHERE t.user_id = %(user_id)s AND c.user_id = %(user_id)s
  AND c.thread_id <> %(thread_id)s
"""


def format_vector(values: Sequence[float]) -> str:
    """Return the text form pgvector parses: `[0.1,-2.5e-05]`."""
    return "[" + ",".join(repr(value) for value in values) + "]"


async def replace_chunks(
    pool: Pool,
    *,
    thread_id: str,
    user_id: int,
    filename: str,
    texts: Sequence[str],
    embeddings: Sequence[Sequence[float]],
) -> None:
    """Swap a thread's chunks for these in one transaction.

    The pool's connections are autocommit, so `transaction()` is what makes the
    delete and the inserts one unit: a bad vector rolls the delete back and the
    old document survives. An advisory lock on the thread id, taken first, makes
    concurrent replaces of one thread take turns, so the last one wins whole.
    """
    rows = [
        {
            "thread_id": thread_id,
            "user_id": user_id,
            "filename": filename,
            "chunk_index": index,
            "content": text,
            "embedding": format_vector(embedding),
        }
        for index, (text, embedding) in enumerate(zip(texts, embeddings), start=1)
    ]
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(LOCK_THREAD, {"thread_id": thread_id})
            await conn.execute(DELETE_THREAD_CHUNKS, {"thread_id": thread_id})
            async with conn.cursor() as cursor:
                await cursor.executemany(INSERT_CHUNK, rows)


async def search_chunks(
    pool: Pool,
    *,
    thread_id: str,
    user_id: int,
    embedding: Sequence[float],
    limit: int,
) -> list[DictRow]:
    """Return the user's `limit` chunks of this thread nearest the embedding, nearest first."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            SELECT_NEAREST_CHUNKS,
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "embedding": format_vector(embedding),
                "limit": limit,
            },
        )
        return await cursor.fetchall()


async def delete_chunks(pool: Pool, *, thread_id: str, user_id: int) -> int:
    """Delete this user's chunks of a thread; return how many went."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            DELETE_USER_CHUNKS, {"thread_id": thread_id, "user_id": user_id}
        )
        return cursor.rowcount


async def read_document_name(pool: Pool, *, thread_id: str, user_id: int) -> str | None:
    """Return the thread's attached filename for this user, or None."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            SELECT_DOCUMENT_NAME, {"thread_id": thread_id, "user_id": user_id}
        )
        row = await cursor.fetchone()
    return row["filename"] if row else None


async def count_live_documents(pool: Pool, *, user_id: int, thread_id: str) -> int:
    """Count the user's other threads that hold a document.

    The join to `chat_threads` leaves out chunks whose thread no longer exists,
    and `thread_id <>` leaves out the thread being replaced.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            COUNT_LIVE_DOCUMENTS, {"user_id": user_id, "thread_id": thread_id}
        )
        row = await cursor.fetchone()
    return int((row or {}).get("documents", 0))
