from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import ormsgpack
import pytest
from langgraph.checkpoint.serde.jsonplus import EXT_CONSTRUCTOR_KW_ARGS

from agents.orchestrator import graph as default_graph
from api import app as app_module
from api.app import app
from models import Source


@pytest.mark.anyio
async def test_lifespan_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    # Arrange
    monkeypatch.setattr(app_module, "init_environment", lambda: None)
    monkeypatch.setattr(app_module, "init_tracing", lambda: None)
    monkeypatch.setattr(app_module, "require_env", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Act
    with patch("api.app.AsyncConnectionPool") as pool:
        # Assert
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            async with app_module.lifespan(app):
                pass
        pool.assert_not_called()


class _FakeCursor:
    """One scripted row for one execute call."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    """The single connection the guard helpers ask the pool for."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def execute(self, statement: str, params: Any = None) -> _FakeCursor:
        return _FakeCursor(self._row)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _FakeGuardPool:
    """Stands in for AsyncConnectionPool where the guards use it."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def connection(self) -> _FakeConn:
        return _FakeConn(self._row)

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_require_migrated_checkpointer_schema_passes_when_public_is_clean() -> (
    None
):
    # Arrange: a fresh or already-migrated database — no public.checkpoints.
    pool: Any = _FakeGuardPool({"stray": None, "target": "agentic"})
    # Act + Assert: no raise
    await app_module._require_migrated_checkpointer_schema(pool)  # assert: no raise


@pytest.mark.anyio
async def test_require_migrated_checkpointer_schema_refuses_a_public_target() -> None:
    # Arrange: no `agentic` schema yet, or search_path never reached the
    # connection — setup() would build its tables in `public`.
    pool: Any = _FakeGuardPool({"stray": None, "target": "public"})
    # Act
    with pytest.raises(RuntimeError, match="make migrate-agentic") as refusal:
        # Arrange
        await app_module._require_migrated_checkpointer_schema(pool)
    # Assert
    assert refusal.type is RuntimeError


@pytest.mark.anyio
async def test_require_migrated_checkpointer_schema_refuses_a_stray_table() -> None:
    # Arrange: the pre-migration state — public.checkpoints still exists.
    pool: Any = _FakeGuardPool({"stray": {"oid": 16384}})
    # Act
    with pytest.raises(RuntimeError, match="make migrate-agentic") as refusal:
        # Arrange
        await app_module._require_migrated_checkpointer_schema(pool)
    # Assert
    assert refusal.type is RuntimeError


@pytest.mark.anyio
async def test_assert_agentic_schema_passes_when_setup_created_both() -> None:
    # Arrange: both setups did their job where search_path should have put them.
    pool: Any = _FakeGuardPool({"checkpoints": {"oid": 16385}, "store": {"oid": 16386}})
    # Act + Assert: no raise
    await app_module._assert_agentic_schema(pool)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "row",
    [
        {"checkpoints": None, "store": {"oid": 16386}},
        {"checkpoints": {"oid": 16385}, "store": None},
    ],
    ids=["store only", "checkpointer only"],
)
async def test_assert_agentic_schema_refuses_a_missing_table(
    row: dict[str, Any],
) -> None:
    # Arrange: the pool's options did not reach the connection.
    pool: Any = _FakeGuardPool(row)
    # Act
    with pytest.raises(RuntimeError, match="search_path") as refusal:
        # Act
        # Assert: the raise is the assertion
        await app_module._assert_agentic_schema(pool)
    assert refusal.type is RuntimeError


@pytest.mark.anyio
async def test_lifespan_checks_the_migration_before_the_checkpointer_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordering is the entire safety property: setup() must not run while
    the checkpointer's tables are still in `public`, or it builds an empty
    second set. A refactor that reorders these calls silently restores the
    history-loss bug."""
    # Arrange
    calls: list[str] = []
    monkeypatch.setattr(app_module, "init_environment", lambda: None)
    monkeypatch.setattr(app_module, "init_tracing", lambda: None)
    monkeypatch.setattr(app_module, "require_env", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://guard:guard@127.0.0.1:5432/g")
    pool: Any = _FakeGuardPool({"stray": None})

    async def require(pool_arg: Any) -> None:
        calls.append("require")

    async def setup() -> None:
        calls.append("checkpointer_setup")

    async def assert_schema(pool_arg: Any) -> None:
        calls.append("assert_schema")

    def build_graph(checkpointer: Any, store: Any = None) -> Any:
        calls.append("graph")
        received["checkpointer"] = checkpointer
        received["store"] = store
        return object()

    monkeypatch.setattr(app_module, "AsyncConnectionPool", lambda *a, **k: pool)
    serdes: list[Any] = []
    received: dict[str, Any] = {}
    store_ttls: list[Any] = []

    def make_saver(pool_arg: Any, serde: Any = None) -> Any:
        serdes.append(serde)
        return type("S", (), {"setup": staticmethod(setup)})()

    def make_store(pool_arg: Any, ttl: Any = None) -> Any:
        store_ttls.append(ttl)

        class _Store:
            async def setup(self) -> None:
                calls.append("store_setup")

            async def start_ttl_sweeper(self) -> None:
                calls.append("sweeper_start")

            async def stop_ttl_sweeper(self) -> None:
                calls.append("sweeper_stop")

        return _Store()

    monkeypatch.setattr(app_module, "AsyncPostgresSaver", make_saver)
    monkeypatch.setattr(app_module, "AsyncPostgresStore", make_store)
    monkeypatch.setattr(app_module, "_require_migrated_checkpointer_schema", require)
    monkeypatch.setattr(app_module, "_assert_agentic_schema", assert_schema)
    monkeypatch.setattr(app_module, "build_graph", build_graph)

    # Act
    async with app_module.lifespan(app):
        # Assert (inside, so the exit paths also run)
        assert calls.index("require") < calls.index("checkpointer_setup")
        assert calls.index("checkpointer_setup") < calls.index("store_setup")
        assert calls.index("store_setup") < calls.index("assert_schema")
        assert calls.index("assert_schema") < calls.index("sweeper_start")
        assert calls.index("sweeper_start") < calls.index("graph")
        assert received["store"] is not None
        assert store_ttls == [app_module.STORE_TTL]
        assert serdes == [app_module.CHECKPOINT_SERDE]
    assert "sweeper_stop" in calls


@pytest.mark.anyio
async def test_store_ttl_is_thirty_days_from_writing() -> None:
    # Act + Assert
    assert app_module.STORE_TTL == {
        "default_ttl": 43_200,
        "refresh_on_read": False,
        "omit_expired": True,
        "sweep_interval_minutes": 60,
    }


@dataclass(frozen=True)
class _Stranger:
    """A custom type that is not on the checkpoint allow-list."""

    value: str


def test_checkpoint_serde_allows_source_and_blocks_other_types(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    # Arrange
    source = Source(title="T", url="https://example.org/a", text="body")
    stranger = _Stranger(value="x")

    # Act
    with caplog.at_level("DEBUG"):
        restored = app_module.CHECKPOINT_SERDE.loads_typed(
            app_module.CHECKPOINT_SERDE.dumps_typed(source)
        )
        blocked = app_module.CHECKPOINT_SERDE.loads_typed(
            app_module.CHECKPOINT_SERDE.dumps_typed(stranger)
        )

    # Assert
    assert restored == source
    assert not isinstance(blocked, _Stranger)
    assert "unregistered" not in caplog.text.lower()


def test_a_checkpointed_source_without_author_still_loads() -> None:
    # Arrange: the payload as the serde wrote a three-field `Source` before
    # `author` existed, rebuilt with dataclass keyword loading.
    payload = ormsgpack.packb(
        ormsgpack.Ext(
            EXT_CONSTRUCTOR_KW_ARGS,
            ormsgpack.packb(
                ("models", "Source", {"title": "t", "url": "u", "text": "x"})
            ),
        )
    )
    # Act
    loaded = app_module.CHECKPOINT_SERDE.loads_typed(("msgpack", payload))
    # Assert
    assert isinstance(loaded, Source)
    assert loaded == Source(title="t", url="u", text="x", author="")


class _FakeStore:
    """The store the lifespan builds, with no database behind it."""

    async def setup(self) -> None:
        pass

    async def start_ttl_sweeper(self) -> None:
        pass

    async def stop_ttl_sweeper(self) -> None:
        pass


class _FakeSaver:
    """The checkpointer the lifespan builds, with no database behind it."""

    async def setup(self) -> None:
        pass


async def _no_schema_check(pool: Any) -> None:
    pass


def test_the_app_serves_the_stream_and_the_thread_routes() -> None:
    """A router the app forgets to include would 404 silently: the app is the only
    place the routes of `routes.py` and `stream.py` are joined."""
    # Arrange
    expected_paths = {
        "/api/health",
        "/api/run_pipeline/stream",
        "/api/threads",
        "/api/threads/{thread_id}",
        "/api/admin/threads/{thread_id}",
    }

    # Act
    served_paths = set(app.openapi()["paths"])

    # Assert
    assert expected_paths <= served_paths


@pytest.mark.anyio
async def test_the_lifespan_serves_the_checkpointer_graph_and_restores_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requests read `app.state.graph`; if the lifespan did not swap in the graph
    built with the checkpointer, every thread would run without history, and if it
    did not swap the default back, the next app would keep a closed pool's graph."""
    # Arrange
    checkpointer_graph = object()
    monkeypatch.setattr(app_module, "init_environment", lambda: None)
    monkeypatch.setattr(app_module, "init_tracing", lambda: None)
    monkeypatch.setattr(app_module, "require_env", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://guard:guard@127.0.0.1:5432/g")
    monkeypatch.setattr(
        app_module, "AsyncConnectionPool", lambda *a, **k: _FakeGuardPool(None)
    )
    monkeypatch.setattr(app_module, "AsyncPostgresSaver", lambda *a, **k: _FakeSaver())
    monkeypatch.setattr(app_module, "AsyncPostgresStore", lambda *a, **k: _FakeStore())
    monkeypatch.setattr(
        app_module, "_require_migrated_checkpointer_schema", _no_schema_check
    )
    monkeypatch.setattr(app_module, "_assert_agentic_schema", _no_schema_check)
    monkeypatch.setattr(
        app_module, "build_graph", lambda checkpointer, store: checkpointer_graph
    )
    graph_before = app.state.graph

    # Act
    async with app_module.lifespan(app):
        graph_inside = app.state.graph
    graph_after = app.state.graph

    # Assert
    assert graph_before is default_graph
    assert graph_inside is checkpointer_graph
    assert graph_after is default_graph
