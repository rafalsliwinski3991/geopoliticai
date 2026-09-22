"""Alembic environment for the schema `agentic_backend` owns.

Django owns `public` and runs its own migrations; nothing here may touch a
Django-owned table. The DSN comes from the root `.env` through
`config.init_environment()` so this file never reads a second source of truth,
and the scheme is rewritten because SQLAlchemy resolves a bare
`postgresql://` to psycopg2, which this project does not install.

`alembic_version` stays in `public` on purpose: Alembic creates it before the
first migration body runs, so pointing `version_table_schema` at `agentic`
would fail on a schema no migration has created yet.
"""

from __future__ import annotations

import logging.config
import os

from alembic import context
from sqlalchemy import create_engine

from config import init_environment

# No ORM models in this project, so autogenerate is unavailable by design.
target_metadata = None

if context.config.config_file_name is not None:
    logging.config.fileConfig(context.config.config_file_name)


def _database_url() -> str:
    """Return the DSN with the psycopg3 dialect the installed driver needs."""
    init_environment()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required to run migrations; it comes from the root .env."
        )
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    # No `future=True`: in SQLAlchemy 2.0 every Engine is 2.0-style and the
    # flag is retained only for backwards compatibility.
    engine = create_engine(_database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
