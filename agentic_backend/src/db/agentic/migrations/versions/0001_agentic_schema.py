"""Create the agentic schema.

Everything `agentic_backend` owns lives here. Django's tables stay in `public`
and are not this migration's business.

Revision ID: 0001_agentic_schema
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001_agentic_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS agentic")


def downgrade() -> None:
    """Drop the schema, refusing if anything still lives in it."""
    # RESTRICT, never CASCADE: if anything is still in here, the operator
    # should have to look at it rather than have it dropped silently.
    op.execute("DROP SCHEMA IF EXISTS agentic RESTRICT")
