"""PostgreSQL integration tests for db/agentic/chunks.py: ordering, scoping, and the transaction."""

import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any, cast

import psycopg
import pytest
from psycopg import connect
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from db.agentic import chunks

DIMENSIONS = 1536
FILENAME = "report.pdf"

if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL must be set for integration tests")


def unit_vector(axis: int) -> list[float]:
    """A 1536-long vector that is 1.0 on one axis and 0.0 elsewhere."""
    return [1.0 if index == axis else 0.0 for index in range(DIMENSIONS)]


def new_thread_id() -> str:
    return f"chunks-{uuid.uuid4().hex}"


@pytest.fixture
def admin() -> Iterator[psycopg.Connection[DictRow]]:
    """A plain connection that creates test users and threads and reads rows back."""
    with connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
        row_factory=dict_row,
        options="-c search_path=agentic,public",
    ) as conn:
        yield conn


@pytest.fixture
def make_user(admin: psycopg.Connection[DictRow]) -> Iterator[Any]:
    """Return a function that inserts a user; everything it made is deleted after."""
    created: list[int] = []

    def make() -> int:
        row = admin.execute(
            """
            INSERT INTO users_user (
                password, is_superuser, is_staff, is_active, date_joined, email,
                first_name, last_name
            )
            VALUES ('integration-test-not-a-real-hash', FALSE, FALSE, TRUE, NOW(), %s, '', '')
            RETURNING id
            """,
            (f"chunks-{os.getpid()}-{time.time_ns()}@example.com",),
        ).fetchone()
        user_id = cast(Any, row)["id"]
        created.append(user_id)
        return int(user_id)

    yield make
    for user_id in created:
        admin.execute("DELETE FROM document_chunks WHERE user_id = %s", (user_id,))
        admin.execute("DELETE FROM chat_threads WHERE user_id = %s", (user_id,))
        admin.execute("DELETE FROM users_user WHERE id = %s", (user_id,))


@pytest.fixture
def make_thread(admin: psycopg.Connection[DictRow]) -> Any:
    def make(user_id: int) -> str:
        thread_id = new_thread_id()
        admin.execute(
            "INSERT INTO chat_threads (id, user_id, title, created_at)"
            " VALUES (%s, %s, 'test', NOW())",
            (thread_id, user_id),
        )
        return thread_id

    return make


@pytest.fixture
async def pool() -> AsyncIterator[chunks.Pool]:
    pool: chunks.Pool = AsyncConnectionPool(
        conninfo=os.environ["DATABASE_URL"],
        min_size=1,
        max_size=2,
        kwargs={
            "row_factory": dict_row,
            "autocommit": True,
            "options": "-c search_path=agentic,public",
        },
        open=False,
    )
    await pool.open()
    yield pool
    await pool.close()


async def put(
    pool: chunks.Pool,
    *,
    thread_id: str,
    user_id: int,
    axes: list[int],
    filename: str = FILENAME,
) -> None:
    await chunks.replace_chunks(
        pool,
        thread_id=thread_id,
        user_id=user_id,
        filename=filename,
        texts=[f"text on axis {axis}" for axis in axes],
        embeddings=[unit_vector(axis) for axis in axes],
    )


def count_rows(admin: psycopg.Connection[DictRow], thread_id: str) -> int:
    row = admin.execute(
        "SELECT count(*) AS n FROM document_chunks WHERE thread_id = %s", (thread_id,)
    ).fetchone()
    return int(cast(Any, row)["n"])


@pytest.mark.anyio
async def test_replacing_a_threads_chunks_removes_the_old_ones(
    pool: chunks.Pool,
    admin: psycopg.Connection[DictRow],
    make_user: Any,
    make_thread: Any,
) -> None:
    """A second upload must leave only the new document's chunks in the thread."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)
    await put(
        pool, thread_id=thread_id, user_id=user_id, axes=[0, 1, 2], filename="old.pdf"
    )

    # Act
    await put(pool, thread_id=thread_id, user_id=user_id, axes=[5], filename="new.pdf")

    # Assert
    rows = admin.execute(
        "SELECT filename, chunk_index FROM document_chunks WHERE thread_id = %s",
        (thread_id,),
    ).fetchall()
    assert rows == [{"filename": "new.pdf", "chunk_index": 1}]


@pytest.mark.anyio
async def test_a_failed_insert_keeps_the_old_chunks(
    pool: chunks.Pool,
    admin: psycopg.Connection[DictRow],
    make_user: Any,
    make_thread: Any,
) -> None:
    """If a new vector is rejected, the delete must roll back so the user keeps the old document."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)
    await put(pool, thread_id=thread_id, user_id=user_id, axes=[0, 1])

    # Act + Assert
    with pytest.raises(psycopg.Error):
        await chunks.replace_chunks(
            pool,
            thread_id=thread_id,
            user_id=user_id,
            filename="new.pdf",
            texts=["good", "bad"],
            embeddings=[unit_vector(3), [1.0, 2.0]],
        )
    assert count_rows(admin, thread_id) == 2
    assert (
        await chunks.read_document_name(pool, thread_id=thread_id, user_id=user_id)
        == FILENAME
    )


@pytest.mark.anyio
async def test_replacing_also_clears_leftovers_a_former_owner_left_under_the_same_thread_id(
    pool: chunks.Pool,
    admin: psycopg.Connection[DictRow],
    make_user: Any,
    make_thread: Any,
) -> None:
    """Chunks outlive a deleted thread; a new owner of a reused id must not inherit them."""
    # Arrange
    former_owner = make_user()
    new_owner = make_user()
    thread_id = make_thread(new_owner)
    await put(pool, thread_id=thread_id, user_id=former_owner, axes=[0, 1])

    # Act
    await put(pool, thread_id=thread_id, user_id=new_owner, axes=[2])

    # Assert
    rows = admin.execute(
        "SELECT user_id FROM document_chunks WHERE thread_id = %s", (thread_id,)
    ).fetchall()
    assert rows == [{"user_id": new_owner}]


@pytest.mark.anyio
async def test_the_nearest_chunk_comes_first(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """Retrieval hands the model the closest passages first."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)
    await put(pool, thread_id=thread_id, user_id=user_id, axes=[0, 1, 2])
    query = unit_vector(2)
    query[1] = 0.5

    # Act
    rows = await chunks.search_chunks(
        pool, thread_id=thread_id, user_id=user_id, embedding=query, limit=3
    )

    # Assert
    assert [row["content"] for row in rows] == [
        "text on axis 2",
        "text on axis 1",
        "text on axis 0",
    ]
    assert rows[0]["chunk_index"] == 3
    assert rows[0]["filename"] == FILENAME


@pytest.mark.anyio
async def test_search_never_returns_another_threads_chunks(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """One thread's document must never answer a question asked in another thread."""
    # Arrange
    user_id = make_user()
    mine = make_thread(user_id)
    other = make_thread(user_id)
    await put(pool, thread_id=mine, user_id=user_id, axes=[0])
    await put(pool, thread_id=other, user_id=user_id, axes=[0])

    # Act
    rows = await chunks.search_chunks(
        pool, thread_id=mine, user_id=user_id, embedding=unit_vector(0), limit=10
    )

    # Assert
    assert len(rows) == 1


@pytest.mark.anyio
async def test_search_never_returns_another_users_chunks(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """Thread ids are client-chosen, so a user who guesses an id must read nothing."""
    # Arrange
    owner = make_user()
    stranger = make_user()
    thread_id = make_thread(owner)
    await put(pool, thread_id=thread_id, user_id=owner, axes=[0])

    # Act
    rows = await chunks.search_chunks(
        pool, thread_id=thread_id, user_id=stranger, embedding=unit_vector(0), limit=10
    )

    # Assert
    assert rows == []


@pytest.mark.anyio
async def test_search_returns_at_most_the_limit(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """The prompt holds a fixed number of excerpts, so the query must stop at the limit."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)
    await put(pool, thread_id=thread_id, user_id=user_id, axes=[0, 1, 2, 3])

    # Act
    rows = await chunks.search_chunks(
        pool, thread_id=thread_id, user_id=user_id, embedding=unit_vector(0), limit=2
    )

    # Assert
    assert len(rows) == 2


@pytest.mark.anyio
async def test_search_in_a_thread_without_chunks_is_empty(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """A thread with no document returns no rows rather than failing."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)

    # Act
    rows = await chunks.search_chunks(
        pool, thread_id=thread_id, user_id=user_id, embedding=unit_vector(0), limit=6
    )

    # Assert
    assert rows == []


@pytest.mark.anyio
async def test_a_threads_document_name_is_read(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """The chat page shows the attached filename."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)
    await put(
        pool, thread_id=thread_id, user_id=user_id, axes=[0, 1], filename="plan.txt"
    )

    # Act
    name = await chunks.read_document_name(pool, thread_id=thread_id, user_id=user_id)

    # Assert
    assert name == "plan.txt"


@pytest.mark.anyio
async def test_a_thread_without_chunks_has_no_document_name(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """No chunks means no document mode."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)

    # Act
    name = await chunks.read_document_name(pool, thread_id=thread_id, user_id=user_id)

    # Assert
    assert name is None


@pytest.mark.anyio
async def test_a_reused_thread_id_does_not_show_the_old_users_document(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """A user who claims a stale thread id must not learn the old owner's filename."""
    # Arrange
    former_owner = make_user()
    new_owner = make_user()
    thread_id = make_thread(new_owner)
    await put(pool, thread_id=thread_id, user_id=former_owner, axes=[0])

    # Act
    name = await chunks.read_document_name(pool, thread_id=thread_id, user_id=new_owner)

    # Assert
    assert name is None


@pytest.mark.anyio
async def test_deleting_a_document_reports_how_many_chunks_went(
    pool: chunks.Pool,
    admin: psycopg.Connection[DictRow],
    make_user: Any,
    make_thread: Any,
) -> None:
    """The caller learns whether anything was removed."""
    # Arrange
    user_id = make_user()
    thread_id = make_thread(user_id)
    await put(pool, thread_id=thread_id, user_id=user_id, axes=[0, 1, 2])

    # Act
    deleted = await chunks.delete_chunks(pool, thread_id=thread_id, user_id=user_id)

    # Assert
    assert deleted == 3
    assert count_rows(admin, thread_id) == 0


@pytest.mark.anyio
async def test_deleting_leaves_another_users_chunks_under_the_same_thread_id(
    pool: chunks.Pool,
    admin: psycopg.Connection[DictRow],
    make_user: Any,
    make_thread: Any,
) -> None:
    """A user's remove request must never erase rows that belong to someone else."""
    # Arrange
    owner = make_user()
    stranger = make_user()
    thread_id = make_thread(owner)
    await put(pool, thread_id=thread_id, user_id=owner, axes=[0, 1])

    # Act
    deleted = await chunks.delete_chunks(pool, thread_id=thread_id, user_id=stranger)

    # Assert
    assert deleted == 0
    assert count_rows(admin, thread_id) == 2


@pytest.mark.anyio
async def test_live_documents_do_not_count_the_current_thread(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """Replacing a thread's document must not count against the cap twice."""
    # Arrange
    user_id = make_user()
    current = make_thread(user_id)
    other = make_thread(user_id)
    await put(pool, thread_id=current, user_id=user_id, axes=[0])
    await put(pool, thread_id=other, user_id=user_id, axes=[0])

    # Act
    count = await chunks.count_live_documents(pool, user_id=user_id, thread_id=current)

    # Assert
    assert count == 1


@pytest.mark.anyio
async def test_live_documents_do_not_count_other_users_threads(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """Another user's documents never fill this user's allowance."""
    # Arrange
    user_id = make_user()
    stranger = make_user()
    current = make_thread(user_id)
    theirs = make_thread(stranger)
    await put(pool, thread_id=theirs, user_id=stranger, axes=[0])

    # Act
    count = await chunks.count_live_documents(pool, user_id=user_id, thread_id=current)

    # Assert
    assert count == 0


@pytest.mark.anyio
async def test_live_documents_do_not_count_orphaned_chunks(
    pool: chunks.Pool,
    admin: psycopg.Connection[DictRow],
    make_user: Any,
    make_thread: Any,
) -> None:
    """Chunks whose thread was deleted are unreachable, so they must not use up the allowance."""
    # Arrange
    user_id = make_user()
    current = make_thread(user_id)
    orphan = make_thread(user_id)
    await put(pool, thread_id=orphan, user_id=user_id, axes=[0])
    admin.execute("DELETE FROM chat_threads WHERE id = %s", (orphan,))

    # Act
    count = await chunks.count_live_documents(pool, user_id=user_id, thread_id=current)

    # Assert
    assert count == 0


@pytest.mark.anyio
async def test_one_document_counts_once_however_many_chunks(
    pool: chunks.Pool, make_user: Any, make_thread: Any
) -> None:
    """The cap is on documents, not on rows."""
    # Arrange
    user_id = make_user()
    current = make_thread(user_id)
    other = make_thread(user_id)
    await put(pool, thread_id=other, user_id=user_id, axes=[0, 1, 2, 3, 4])

    # Act
    count = await chunks.count_live_documents(pool, user_id=user_id, thread_id=current)

    # Assert
    assert count == 1
