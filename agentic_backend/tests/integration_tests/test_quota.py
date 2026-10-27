import os
import time
from datetime import date
from typing import Any, cast

import pytest
from psycopg import AsyncConnection, connect
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from api import quota as quota_module
from db.web import sql
from shared.config import DAILY_RESEARCH_TURNS
from shared.errors import QuotaExceededError

# A fixed past day: the real counters for today are never touched.
DAY = date(1971, 1, 4)


@pytest.mark.anyio
async def test_a_refused_user_charge_keeps_the_site_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On real Postgres, the site is charged before the user: a user at their cap
    is refused, and the site unit the turn already took stays spent."""

    # Arrange
    monkeypatch.setattr(sql, "quota_day", lambda: DAY)
    monkeypatch.setattr(quota_module, "quota_day", lambda: DAY)
    url = os.environ["DATABASE_URL"]
    with connect(url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users_user (
                    password, is_superuser, is_staff, is_active, date_joined, email,
                    first_name, last_name
                )
                VALUES (
                    'integration-test-not-a-real-hash', FALSE, FALSE, TRUE, NOW(), %s,
                    '', ''
                )
                RETURNING id
                """,
                (f"quota-{os.getpid()}-{time.time_ns()}@example.com",),
            )
            user_id = cast(Any, cursor.fetchone())["id"]
            cursor.execute(
                "INSERT INTO quota (user_id, day, used) VALUES (%s, %s, %s)",
                (user_id, DAY, DAILY_RESEARCH_TURNS),
            )
        try:
            pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=2,
                kwargs={"row_factory": dict_row},
                open=False,
            )
            await pool.open()
            try:
                # Act + Assert
                with pytest.raises(QuotaExceededError):
                    await quota_module.charge_turn(
                        pool, user_id=user_id, destination=None
                    )
            finally:
                await pool.close()

            # Assert
            with conn.cursor() as cursor:
                cursor.execute("SELECT used FROM site_quota WHERE day = %s", (DAY,))
                site_used = cast(Any, cursor.fetchone())["used"]
                cursor.execute(
                    "SELECT used FROM quota WHERE user_id = %s AND day = %s",
                    (user_id, DAY),
                )
                user_used = cast(Any, cursor.fetchone())["used"]
            assert site_used == 1
            assert user_used == DAILY_RESEARCH_TURNS
        finally:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM site_quota WHERE day = %s", (DAY,))
                cursor.execute("DELETE FROM quota WHERE user_id = %s", (user_id,))
                cursor.execute("DELETE FROM users_user WHERE id = %s", (user_id,))
