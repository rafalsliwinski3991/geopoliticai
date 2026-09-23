"""Drop an empty duplicate set of checkpointer tables left in public.

Something that runs the checkpointer's `setup()` without the pool's
`agentic,public` search_path (a local `langgraph dev`, a test) builds a fresh,
empty set in `public` after `0002_checkpointer_to_agentic` has already moved
the real ones. The API's startup guard then refuses to boot.

Only acts when the real set exists in `agentic`, and refuses when the `public`
copy holds any thread data, so it can never drop history.

Revision ID: 0003_drop_stray_public_tables
Revises: 0002_checkpointer_to_agentic
"""

from __future__ import annotations

from alembic import op

revision = "0003_drop_stray_public_tables"
down_revision = "0002_checkpointer_to_agentic"
branch_labels = None
depends_on = None

# `checkpoint_migrations` always holds setup()'s version rows, so it is dropped
# but not checked for emptiness.
DATA_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")
TABLES = ("checkpoint_migrations", *DATA_TABLES)


def upgrade() -> None:
    """Drop the public checkpointer tables when they are an empty duplicate."""
    checks = "\n".join(
        f"""
            IF to_regclass('public.{table}') IS NOT NULL
               AND EXISTS (SELECT 1 FROM public.{table}) THEN
                RAISE EXCEPTION
                    'public.{table} holds rows, so it is not an empty duplicate. '
                    'Inspect it against agentic.{table} before dropping anything.';
            END IF;"""
        for table in DATA_TABLES
    )
    drops = "\n".join(
        f"            DROP TABLE IF EXISTS public.{table};" for table in TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('agentic.checkpoints') IS NULL THEN
                RETURN;
            END IF;
{checks}
{drops}
        END $$;
        """
    )


def downgrade() -> None:
    """Nothing to restore: the dropped tables were empty duplicates."""
