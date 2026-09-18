"""Unit tests for the raw-psycopg threads module (units 5, 6)."""

from typing import Any, cast

import pytest

import threads
from threads import (
    ThreadRow,
    claim_thread,
    is_staff,
    list_threads,
    owns_thread,
    title_from,
)

ROWS: dict[str, list[dict[str, Any]]] = {}


class _FakeCursor:
    """Returns what the test scripted, one statement at a time."""

    def __init__(self, conn: "_FakeConnection") -> None:
        self._conn = conn

    async def fetchone(self) -> dict[str, Any] | None:
        rows = self._conn.executed_rows[-1]
        return rows[0] if rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._conn.executed_rows[-1]


class _FakeConnection:
    def __init__(self, scripted_rows: dict[str, list[dict[str, Any]]]) -> None:
        self.scripted_rows = scripted_rows
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.executed_rows: list[list[dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakeConnection":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, statement: str, params: dict[str, Any]) -> _FakeCursor:
        self.executed.append((statement, params))
        self.executed_rows.append(self.scripted_rows.get(statement, []))
        return _FakeCursor(self)


class _FakePool:
    def __init__(self, scripted_rows: dict[str, list[dict[str, Any]]]) -> None:
        self.conn = _FakeConnection(scripted_rows)

    def connection(self) -> _FakeConnection:
        return self.conn


def pool(fake: _FakePool) -> Any:
    """The fakes structurally match what the helpers touch, not psycopg."""
    return cast(Any, fake)


@pytest.fixture
def seen(_fake_pool: _FakePool) -> list[tuple[str, dict[str, Any]]]:
    return _fake_pool.conn.executed


@pytest.fixture
def _fake_pool() -> _FakePool:
    return _FakePool({})


def test_title_from_truncates_and_collapses_whitespace() -> None:
    assert (
        title_from("  a\t b  " * 20)
        == ("a b " * 20).strip()[: threads.MAX_TITLE_LENGTH]
    )
    assert len(title_from("a b " * 40)) == threads.MAX_TITLE_LENGTH


def test_title_from_of_an_empty_query_is_empty() -> None:
    assert title_from("") == ""


@pytest.mark.anyio
async def test_claim_thread_reports_true_for_a_new_thread(
    _fake_pool: _FakePool, seen: list[tuple[str, dict[str, Any]]]
) -> None:
    _fake_pool.conn.scripted_rows = {threads.SELECT_THREAD_OWNER: [{"user_id": 7}]}
    assert await claim_thread(
        pool(_fake_pool), thread_id="t1", user_id=7, title="Question"
    )
    statements = [statement for statement, _ in seen]
    assert statements == [threads.UPSERT_THREAD, threads.SELECT_THREAD_OWNER]
    assert seen[0][1] == {"thread_id": "t1", "user_id": 7, "title": "Question"}


@pytest.mark.anyio
async def test_claim_thread_reports_true_for_the_owners_second_turn(
    _fake_pool: _FakePool,
) -> None:
    _fake_pool.conn.scripted_rows = {threads.SELECT_THREAD_OWNER: [{"user_id": 7}]}
    assert await claim_thread(pool(_fake_pool), thread_id="t1", user_id=7, title=None)


@pytest.mark.anyio
async def test_claim_thread_reports_false_for_another_users_thread(
    _fake_pool: _FakePool,
) -> None:
    _fake_pool.conn.scripted_rows = {threads.SELECT_THREAD_OWNER: [{"user_id": 8}]}
    assert not await claim_thread(
        pool(_fake_pool), thread_id="t1", user_id=7, title=None
    )


@pytest.mark.anyio
async def test_claim_thread_reports_false_for_an_unknown_thread(
    _fake_pool: _FakePool,
) -> None:
    _fake_pool.conn.scripted_rows = {threads.SELECT_THREAD_OWNER: []}
    assert not await claim_thread(
        pool(_fake_pool), thread_id="t1", user_id=7, title=None
    )


@pytest.mark.anyio
async def test_owns_thread_reads_the_owner_without_upserting(
    _fake_pool: _FakePool, seen: list[tuple[str, dict[str, Any]]]
) -> None:
    _fake_pool.conn.scripted_rows = {threads.SELECT_THREAD_OWNER: [{"user_id": 7}]}
    assert await owns_thread(pool(_fake_pool), thread_id="t1", user_id=7)
    assert [statement for statement, _ in seen] == [threads.SELECT_THREAD_OWNER]


@pytest.mark.anyio
async def test_list_threads_maps_rows_for_the_sidebar(_fake_pool: _FakePool) -> None:
    _fake_pool.conn.scripted_rows = {
        threads.SELECT_THREADS: [
            {"id": "t1", "title": "NATO", "created_at": "2026-09-18T10:00:00Z"}
        ]
    }
    rows = await list_threads(pool(_fake_pool), user_id=7)
    assert rows == [ThreadRow(id="t1", title="NATO", created_at="2026-09-18T10:00:00Z")]


@pytest.mark.anyio
async def test_is_staff_reads_the_database(_fake_pool: _FakePool) -> None:
    _fake_pool.conn.scripted_rows = {threads.SELECT_IS_STAFF: [{"is_staff": True}]}
    assert await is_staff(pool(_fake_pool), user_id=1)
    _fake_pool.conn.scripted_rows = {threads.SELECT_IS_STAFF: [{"is_staff": False}]}
    assert not await is_staff(pool(_fake_pool), user_id=1)
    _fake_pool.conn.scripted_rows = {threads.SELECT_IS_STAFF: []}
    assert not await is_staff(pool(_fake_pool), user_id=1)
