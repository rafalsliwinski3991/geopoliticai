"""PostgreSQL integration tests for Alembic revision behavior."""

import importlib
import os

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import connect
from psycopg.rows import dict_row

SEARCH_PATH_OPTION = "-c search_path=agentic,public"
CHECKPOINTER_TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)

if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL must be set for integration tests")


def test_stray_table_migration_skips_absent_public_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The revision runs after 0002 when its source tables are absent."""
    migration = importlib.import_module(
        "db.agentic.migrations.versions.0003_drop_stray_public_tables"
    )

    with connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=SEARCH_PATH_OPTION,
    ) as conn:
        row = conn.execute("SELECT current_schema() AS target").fetchone()
        assert row is not None
        assert row["target"] == "agentic", "run `make migrate-agentic` first"

        PostgresSaver(conn).setup()
        row = conn.execute(
            "SELECT to_regclass('agentic.checkpoints') AS relation"
        ).fetchone()
        assert row is not None
        assert row["relation"] is not None

        for table in CHECKPOINTER_TABLES:
            row = conn.execute(
                "SELECT to_regclass(%s) AS relation", (f"public.{table}",)
            ).fetchone()
            assert row is not None
            assert row["relation"] is None

        def execute(statement: str) -> None:
            with conn.cursor() as cursor:
                cursor.execute(statement)

        monkeypatch.setattr(migration.op, "execute", execute)

        migration.upgrade()
