"""What a research turn costs, and how it is charged and given back.

The rules CLAUDE.md's Quota section states, in one module: one commit at a time
per user, the advisory headroom read for a costly turn, the site charged before
the user, and the capped refund of a failed turn. `api._generate` calls
`charge_turn` once the classifier picks a research branch and `refund_turn` on
every error frame.
"""

from __future__ import annotations

import logging
from asyncio import Lock
from dataclasses import dataclass
from datetime import date

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

from config import (
    DAILY_RESEARCH_TURNS,
    DAILY_RESEARCH_TURNS_ALL_USERS,
    DEEP_RESEARCH_TURN_COST,
    FORECAST_TURN_COST,
    MAX_DAILY_REFUND_UNITS,
)
from db.web.sql import (
    increment_quota,
    increment_site_quota,
    quota_day,
    quota_used,
    refund_quota,
)
from models import QuotaExceededError

logger = logging.getLogger(__name__)

# The research destinations that spend more than one unit, each with the
# refusal the advisory headroom read gives a caller who cannot afford it
# (brainstorm 2026Sep28 Q3; 2026Sep30 Q22). Every other research destination
# spends one unit, and `ONE_UNIT`'s empty refusal is never shown.
COSTLY_DESTINATIONS: dict[str, tuple[int, str]] = {
    "deep": (
        DEEP_RESEARCH_TURN_COST,
        "A deep analysis needs {cost} research turns; you have {left} left today.",
    ),
    "forecast": (
        FORECAST_TURN_COST,
        "A forecast needs {cost} research turns; you have {left} left today.",
    ),
}
ONE_UNIT: tuple[int, str] = (1, "")
SITE_LIMIT_MESSAGE = "The site has used today's research capacity."
USER_LIMIT_MESSAGE = "Daily research limit reached."
# One costly-turn commit at a time per user (review thread, #148): the advisory
# headroom read cannot be raced, but the site upsert can, so a burst of
# concurrent forecast requests must not each take `cost` site units before the
# user's own upsert disqualifies all but one (see `charge_turn`).
_turn_locks: dict[int, Lock] = {}
# Units refunded per (user, UTC day), for the daily refund cap. In process
# memory, like `api._rate_limit_store`: a restart forgets it, which allows at
# most one more capped refund per user per restart (user decision 2026-10-16).
_refunded_units: dict[tuple[int, date], int] = {}


@dataclass(frozen=True)
class Charge:
    """What one turn took from the user's own counter, and on which quota day."""

    day: date
    cost: int


def _turn_lock(user_id: int) -> Lock:
    """Return the per-user lock serializing a counted turn's quota commit."""
    return _turn_locks.setdefault(user_id, Lock())


async def charge_turn(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    *,
    user_id: int,
    destination: str | None,
) -> Charge:
    """Charge one research turn to the site, then to the user; raise when either is full.

    `destination` is the classifier's branch; None (test fakes) is a one-unit
    turn.
    """
    cost, refusal = (
        COSTLY_DESTINATIONS.get(destination, ONE_UNIT) if destination else ONE_UNIT
    )
    async with _turn_lock(user_id):
        if cost > 1:
            # Advisory headroom check before the site is charged (plan review):
            # without it, a user at 17/20 retrying a costly request (deep or
            # forecast) spends its cost in site units per refused retry, and a
            # few dozen retries exhaust the 500-unit site ceiling for everyone.
            # The user upsert below still decides; this read only stops the
            # obviously unaffordable turn early. Refused, not downgraded (Q8A).
            left = DAILY_RESEARCH_TURNS - await quota_used(pool, user_id=user_id)
            if left < cost:
                raise QuotaExceededError(refusal.format(cost=cost, left=max(0, left)))
        # The site ceiling is committed before the caller is charged: a turn the
        # site refuses must not cost the user their own turn, and unlike an
        # advisory pre-read the conditional upsert cannot be raced open — the
        # database decides, so no concurrent turn can still take the last slot
        # between a read and this write.
        if not await increment_site_quota(
            pool, limit=DAILY_RESEARCH_TURNS_ALL_USERS, cost=cost
        ):
            # The site-wide ceiling: the operator's bill has a second, coarser
            # bound no single account controls. Chat turns never reach here (Q5b).
            raise QuotaExceededError(SITE_LIMIT_MESSAGE)
        day = quota_day()
        if not await increment_quota(
            pool, user_id=user_id, day=day, limit=DAILY_RESEARCH_TURNS, cost=cost
        ):
            # A concurrent turn took the last one (for a costly turn: took units
            # between the headroom read and here). The site slot just taken
            # belongs to this run's own refusal: the user is not charged for a
            # turn that never produces an answer, and the site count stays
            # honest about the run that did happen.
            raise QuotaExceededError(USER_LIMIT_MESSAGE)
    return Charge(day=day, cost=cost)


async def refund_turn(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]], *, user_id: int, charge: Charge
) -> None:
    """Give a failed turn's units back, unless the user's daily refund cap is spent.

    The cap is reserved before the await, so two failures finishing at once
    cannot both pass it. A failed refund is logged and swallowed, and gives
    its reservation back: the user is about to get the turn's real error, and
    this must not replace it — nor spend the day's cap for nothing.
    """
    day, cost = charge.day, charge.cost
    for stale in [key for key in _refunded_units if key[1] < day]:
        del _refunded_units[stale]
    refunded = _refunded_units.get((user_id, day), 0)
    if refunded + cost > MAX_DAILY_REFUND_UNITS:
        logger.info("Refund of %d units refused: the daily refund cap is spent.", cost)
        return
    _refunded_units[(user_id, day)] = refunded + cost
    try:
        await refund_quota(pool, user_id=user_id, day=day, cost=cost)
    except Exception:  # noqa: BLE001 - logged; the turn's own error wins
        logger.exception("Refunding %d research units failed.", cost)
        # Subtracting, not restoring the value read above: another coroutine
        # may have reserved since, and each failure removes only its own add.
        left = _refunded_units.get((user_id, day), 0) - cost
        if left > 0:
            _refunded_units[(user_id, day)] = left
        else:
            _refunded_units.pop((user_id, day), None)
        return
    logger.info("Refunded %d research units to the day %s.", cost, day)
