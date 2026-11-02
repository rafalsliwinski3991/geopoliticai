"""Unit tests for the pure part of db/agentic/chunks.py; the SQL is in the integration tests."""

from typing import Any

import pytest

from db.agentic.chunks import (
    DELETE_THREAD_CHUNKS,
    INSERT_CHUNK,
    LOCK_THREAD,
    format_vector,
    replace_chunks,
)


class RecordingConnection:
    """A connection that records each statement it is given, in order."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def __aenter__(self) -> "RecordingConnection":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def transaction(self) -> "RecordingConnection":
        return self

    def cursor(self) -> "RecordingConnection":
        return self

    async def execute(self, statement: str, params: Any = None) -> None:
        self.statements.append(statement)

    async def executemany(self, statement: str, rows: Any) -> None:
        self.statements.append(statement)


class RecordingPool:
    def __init__(self, conn: RecordingConnection) -> None:
        self.conn = conn

    def connection(self) -> RecordingConnection:
        return self.conn


def test_a_vector_is_written_as_a_bracketed_list() -> None:
    """pgvector parses `[a,b,c]` text, and the pool registers no adapter, so
    the vector must reach the database in exactly this form."""
    # Arrange
    values = [0.1, -2.5, 3.0]

    # Act
    text = format_vector(values)

    # Assert
    assert text == "[0.1,-2.5,3.0]"


def test_a_vector_keeps_small_exponents() -> None:
    """A tiny component printed as 0.0 would silently change the embedding."""
    # Arrange
    values = [2.5e-05, -1e-07]

    # Act
    text = format_vector(values)

    # Assert
    assert text == "[2.5e-05,-1e-07]"


@pytest.mark.anyio
async def test_replacing_chunks_locks_the_thread_before_it_deletes_or_inserts() -> None:
    """Two uploads to one thread would otherwise both delete, then both insert, and mix documents."""
    # Arrange
    conn = RecordingConnection()

    # Act
    await replace_chunks(
        RecordingPool(conn),  # type: ignore[arg-type]
        thread_id="t1",
        user_id=1,
        filename="a.txt",
        texts=["x"],
        embeddings=[[0.5]],
    )

    # Assert
    assert conn.statements == [LOCK_THREAD, DELETE_THREAD_CHUNKS, INSERT_CHUNK]


def test_the_thread_lock_is_a_transaction_scoped_advisory_lock_on_the_thread_id() -> (
    None
):
    """A transaction lock frees itself on commit or rollback, so a crash cannot leave a thread locked."""
    # Arrange
    expected = "SELECT pg_advisory_xact_lock(hashtext(%(thread_id)s))"

    # Act
    statement = LOCK_THREAD

    # Assert
    assert statement == expected
