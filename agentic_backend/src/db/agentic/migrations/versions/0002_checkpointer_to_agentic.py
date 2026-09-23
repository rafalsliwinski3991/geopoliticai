"""Move LangGraph's checkpointer tables into the agentic schema.

LangGraph creates these four tables and owns their DDL. Alembic only relocates
them and must never generate, alter or drop them; autogenerate is off in this
project for exactly this reason.

Guarded both ways so it is a no-op on a fresh database, where nothing exists in
`public` yet and the checkpointer's own `setup()` will create them directly in
`agentic` because of the pool's search_path.

Revision ID: 0002_checkpointer_to_agentic
Revises: 0001_agentic_schema
"""

from __future__ import annotations

from alembic import op

revision = "0002_checkpointer_to_agentic"
down_revision = "0001_agentic_schema"
branch_labels = None
depends_on = None

# `checkpoint_migrations` carries the checkpointer's own version integer. It has
# no thread_id and nothing deletes from it, but it must travel with the others
# or `setup()` will believe the schema is unmigrated.
TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)


def _move(table: str, source: str, target: str) -> None:
    """Relocate one table, refusing loudly when two copies already exist.

    The both-exist case means a service ran `setup()` before this migration
    and created an empty duplicate. Silently doing nothing there is what turns
    a recoverable mistake into an unbootable service with no documented exit.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('{source}.{table}') IS NOT NULL
               AND to_regclass('{target}.{table}') IS NOT NULL THEN
                RAISE EXCEPTION
                    'Both {source}.{table} and {target}.{table} exist. A service '
                    'was started before this migration ran and created an empty '
                    'duplicate. Inspect both, drop the empty one, and retry.';
            END IF;
            IF to_regclass('{source}.{table}') IS NOT NULL THEN
                ALTER TABLE {source}.{table} SET SCHEMA {target};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    """Move the four checkpointer tables from public into agentic."""
    for table in TABLES:
        _move(table, "public", "agentic")


def downgrade() -> None:
    """Move the four checkpointer tables back into public."""
    for table in TABLES:
        _move(table, "agentic", "public")
