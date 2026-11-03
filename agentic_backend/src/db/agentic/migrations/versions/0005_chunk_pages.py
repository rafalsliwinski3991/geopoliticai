"""Record the first and last page of each uploaded chunk.

Revision ID: 0005_chunk_pages
Revises: 0004_document_chunks
"""

from __future__ import annotations

from alembic import op

revision = "0005_chunk_pages"
down_revision = "0004_document_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the page range.

    Both stay NULL for a text file and for chunks stored before this revision,
    which are cited by chunk number.
    """
    op.execute(
        "ALTER TABLE agentic.document_chunks"
        " ADD COLUMN page_start integer, ADD COLUMN page_end integer"
    )


def downgrade() -> None:
    """Drop the page range."""
    op.execute(
        "ALTER TABLE agentic.document_chunks"
        " DROP COLUMN page_start, DROP COLUMN page_end"
    )
