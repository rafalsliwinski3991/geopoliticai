"""Tests that need a real, Django-migrated Postgres — everything else is a unit test.

`agentic_backend/` owns no schema and runs no migrations. It addresses Django's
tables by name in raw SQL (`src/db/web/sql.py`), so nothing at import time, and no
amount of mocking, notices when a `web_backend` migration renames a column. The
statement is a string until Postgres parses it. These tests are the only place
that parsing happens before production does it.

A test belongs here when its subject is the boundary between the two services:
the shape of a Django-owned table, a delete path that crosses from the ORM into
the checkpointer's tables, or a query whose correctness is a property of the
database rather than of the code. Everything else belongs in `tests/unit_tests/`,
which must stay hermetic and fast.

Requires `DATABASE_URL` pointing at a database migrated by both `make migrate-web`
and `make migrate-agentic` (from the repository root). The checkpointer's own
tables are created by the tests, idempotently, in the `agentic` schema. Without
`DATABASE_URL` every test here skips, so a green run proves nothing at all —
check for the skip count before believing one.

    cd agentic_backend && make test-integration

These tests write to a shared development database and clean up after
themselves. A test that mutates state it did not create restores it visibly, in
the test body, rather than in a fixture teardown.
"""
