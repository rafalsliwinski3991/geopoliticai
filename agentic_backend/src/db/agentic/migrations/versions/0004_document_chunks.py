"""Create the uploaded documents' chunk table.

Revision ID: 0004_document_chunks
Revises: 0003_drop_stray_public_tables
"""

from __future__ import annotations

from alembic import op

revision = "0004_document_chunks"
down_revision = "0003_drop_stray_public_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add pgvector and the table.

    The extension goes to `public`, which the pool's `search_path`
    (`agentic,public`) always reaches.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    op.execute(
        """
        CREATE TABLE agentic.document_chunks (
            id bigserial PRIMARY KEY,
            thread_id text NOT NULL,
            user_id integer NOT NULL,
            filename text NOT NULL,
            chunk_index integer NOT NULL,
            content text NOT NULL,
            embedding public.vector(1536) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX document_chunks_thread_id_idx"
        " ON agentic.document_chunks (thread_id)"
    )


def downgrade() -> None:
    """Drop the table; the extension stays, since other tables may use it later."""
    op.execute("DROP TABLE IF EXISTS agentic.document_chunks")
