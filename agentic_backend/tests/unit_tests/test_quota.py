import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, cast

import pytest
from psycopg.errors import OperationalError

import quota as quota_module
from config import (
    DAILY_RESEARCH_TURNS,
    DAILY_RESEARCH_TURNS_ALL_USERS,
    DEEP_RESEARCH_TURN_COST,
    FORECAST_TURN_COST,
    MAX_DAILY_REFUND_UNITS,
)
from models import QuotaExceededError
from quota import Charge, charge_turn, refund_turn

CHARGE_DAY = date(2026, 10, 16)
TOMORROW = CHARGE_DAY + timedelta(days=1)
# The fakes never touch the pool, so the tests pass none.
POOL = cast(Any, None)


@dataclass
class RecordingQuota:
    """Stands in for the quota reads and writes and records every write in order.

    `used` is what the headroom read reports. `user_has_room` and `site_has_room`
    set to False refuse the matching increment, as the conditional upsert does at
    its cap.
    """

    used: int = 0
    user_has_room: bool = True
    site_has_room: bool = True
    refund_error: BaseException | None = None
    reads: list[int] = field(default_factory=list)
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    async def quota_used(self, pool: Any, *, user_id: int) -> int:
        self.reads.append(user_id)
        return self.used

    async def increment_quota(
        self, pool: Any, *, user_id: int, day: date, limit: int, cost: int = 1
    ) -> int | None:
        self.calls.append(("user", user_id, day, limit, cost))
        return cost if self.user_has_room else None

    async def increment_site_quota(
        self, pool: Any, *, limit: int, cost: int = 1
    ) -> int | None:
        self.calls.append(("site", limit, cost))
        return cost if self.site_has_room else None

    async def refund_quota(
        self, pool: Any, *, user_id: int, day: date, cost: int
    ) -> None:
        self.calls.append(("refund", user_id, day, cost))
        if self.refund_error is not None:
            raise self.refund_error

    def refunds(self) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == "refund"]


@pytest.fixture(autouse=True)
def quota(monkeypatch: pytest.MonkeyPatch) -> RecordingQuota:
    """Every counter has room, today is CHARGE_DAY, and the refund ledger is empty,
    unless a test says otherwise."""
    recording = RecordingQuota()
    monkeypatch.setattr(quota_module, "quota_used", recording.quota_used)
    monkeypatch.setattr(quota_module, "increment_quota", recording.increment_quota)
    monkeypatch.setattr(
        quota_module, "increment_site_quota", recording.increment_site_quota
    )
    monkeypatch.setattr(quota_module, "refund_quota", recording.refund_quota)
    monkeypatch.setattr(quota_module, "quota_day", lambda: CHARGE_DAY)
    quota_module._refunded_units.clear()
    return recording


@pytest.mark.anyio
async def test_a_research_turn_charges_the_site_then_the_user(
    quota: RecordingQuota,
) -> None:
    """A one-unit research turn takes one unit from the site, then one from the user."""

    # Arrange
    # Act
    await charge_turn(POOL, user_id=1, destination="geopolitical")

    # Assert
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1),
    ]


@pytest.mark.anyio
async def test_a_deep_turn_spends_the_deep_cost(quota: RecordingQuota) -> None:
    """A deep analysis costs DEEP_RESEARCH_TURN_COST units from both counters."""

    # Arrange
    # Act
    await charge_turn(POOL, user_id=1, destination="deep")

    # Assert
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, DEEP_RESEARCH_TURN_COST),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, DEEP_RESEARCH_TURN_COST),
    ]


@pytest.mark.anyio
async def test_a_forecast_spends_the_forecast_cost(quota: RecordingQuota) -> None:
    """A forecast costs FORECAST_TURN_COST units from both counters."""

    # Arrange
    # Act
    await charge_turn(POOL, user_id=1, destination="forecast")

    # Assert
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, FORECAST_TURN_COST),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, FORECAST_TURN_COST),
    ]


@pytest.mark.anyio
async def test_a_costly_turn_without_headroom_touches_no_counter(
    quota: RecordingQuota,
) -> None:
    """The advisory headroom read refuses a deep turn that cannot fit, before the
    site is charged, so a refused retry spends nothing from the site's ceiling."""

    # Arrange
    quota.used = DAILY_RESEARCH_TURNS - DEEP_RESEARCH_TURN_COST + 1

    # Act
    with pytest.raises(QuotaExceededError) as refused:
        await charge_turn(POOL, user_id=1, destination="deep")

    # Assert
    assert str(refused.value) == (
        "A deep analysis needs 10 research turns; you have 9 left today."
    )
    assert quota.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("destination", "used", "refusal"),
    [
        (
            "deep",
            DAILY_RESEARCH_TURNS - 9,
            "A deep analysis needs 10 research turns; you have 9 left today.",
        ),
        (
            "forecast",
            DAILY_RESEARCH_TURNS - 19,
            "A forecast needs 20 research turns; you have 19 left today.",
        ),
    ],
    ids=["deep", "forecast"],
)
async def test_a_costly_refusal_names_its_own_cost(
    quota: RecordingQuota, destination: str, used: int, refusal: str
) -> None:
    """The refusal tells the user what the turn costs and how much they have left,
    in the words of its own destination."""

    # Arrange
    quota.used = used

    # Act
    with pytest.raises(QuotaExceededError) as refused:
        await charge_turn(POOL, user_id=1, destination=destination)

    # Assert
    assert str(refused.value) == refusal


@pytest.mark.anyio
async def test_a_costly_turn_exactly_at_the_headroom_is_charged(
    quota: RecordingQuota,
) -> None:
    """The boundary `left == cost` is affordable: only `left < cost` is refused."""

    # Arrange
    quota.used = DAILY_RESEARCH_TURNS - DEEP_RESEARCH_TURN_COST

    # Act
    await charge_turn(POOL, user_id=1, destination="deep")

    # Assert
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, DEEP_RESEARCH_TURN_COST),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, DEEP_RESEARCH_TURN_COST),
    ]


@pytest.mark.anyio
async def test_a_refused_site_charge_leaves_the_user_counter_untouched(
    quota: RecordingQuota,
) -> None:
    """A full site refuses the turn before the user is charged, so the user keeps
    their own units."""

    # Arrange
    quota.site_has_room = False

    # Act
    with pytest.raises(QuotaExceededError) as refused:
        await charge_turn(POOL, user_id=1, destination="geopolitical")

    # Assert
    assert str(refused.value) == "The site has used today's research capacity."
    assert quota.calls == [("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1)]


@pytest.mark.anyio
async def test_a_lost_user_race_keeps_the_site_units_spent(
    quota: RecordingQuota,
) -> None:
    """A user who loses the upsert race gets the generic limit message, and the
    site units already taken stay spent: nothing is refunded for a refused charge."""

    # Arrange
    quota.user_has_room = False

    # Act
    with pytest.raises(QuotaExceededError) as refused:
        await charge_turn(POOL, user_id=1, destination="forecast")

    # Assert
    assert str(refused.value) == "Daily research limit reached."
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, FORECAST_TURN_COST),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, FORECAST_TURN_COST),
    ]


@pytest.mark.anyio
async def test_an_unnamed_destination_costs_one_unit(quota: RecordingQuota) -> None:
    """A turn with no destination (the test fakes' shape) is an ordinary one-unit turn."""

    # Arrange
    # Act
    charge = await charge_turn(POOL, user_id=1, destination=None)

    # Assert
    assert charge == Charge(day=CHARGE_DAY, cost=1)
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1),
    ]


@pytest.mark.anyio
async def test_the_charge_records_its_quota_day(quota: RecordingQuota) -> None:
    """The charge keeps the day it was taken, so a refund can give the units back
    to that day even after midnight UTC."""

    # Arrange
    # Act
    charge = await charge_turn(POOL, user_id=1, destination="forecast")

    # Assert
    assert charge == Charge(day=CHARGE_DAY, cost=FORECAST_TURN_COST)


@pytest.mark.anyio
async def test_a_refund_goes_to_the_charge_day(
    monkeypatch: pytest.MonkeyPatch, quota: RecordingQuota
) -> None:
    """The units go back to the charge's day, not to today: a forecast that
    straddles midnight UTC must not pay back the wrong day."""

    # Arrange
    monkeypatch.setattr(quota_module, "quota_day", lambda: TOMORROW)
    charge = Charge(day=CHARGE_DAY, cost=FORECAST_TURN_COST)

    # Act
    await refund_turn(POOL, user_id=1, charge=charge)

    # Assert
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, FORECAST_TURN_COST)]


@pytest.mark.anyio
async def test_refunds_stop_at_the_daily_cap(quota: RecordingQuota) -> None:
    """A user's refunds stop at MAX_DAILY_REFUND_UNITS a day, so a user who can
    force failures cannot spend the site's ceiling for free all day."""

    # Arrange
    charge = Charge(day=CHARGE_DAY, cost=1)
    for _ in range(MAX_DAILY_REFUND_UNITS):
        await refund_turn(POOL, user_id=1, charge=charge)

    # Act
    await refund_turn(POOL, user_id=1, charge=charge)

    # Assert
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, 1)] * MAX_DAILY_REFUND_UNITS


@pytest.mark.anyio
async def test_a_failed_refund_gives_the_cap_back(quota: RecordingQuota) -> None:
    """A refund write that fails does not spend the day's cap: the reservation is
    kept only when the units actually went back."""

    # Arrange
    quota.refund_error = OperationalError("db down")

    # Act
    await refund_turn(POOL, user_id=1, charge=Charge(day=CHARGE_DAY, cost=1))

    # Assert
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, 1)]
    assert quota_module._refunded_units == {}


@pytest.mark.anyio
async def test_a_failed_refund_is_logged_under_the_quota_logger(
    quota: RecordingQuota, caplog: pytest.LogCaptureFixture
) -> None:
    """A refund the database refuses is logged and swallowed, under the quota
    logger, so the turn's own error still reaches the browser."""

    # Arrange
    quota.refund_error = OperationalError("db down")

    # Act
    with caplog.at_level(logging.ERROR, logger="quota"):
        await refund_turn(POOL, user_id=1, charge=Charge(day=CHARGE_DAY, cost=20))

    # Assert
    assert [(record.name, record.getMessage()) for record in caplog.records] == [
        ("quota", "Refunding 20 research units failed.")
    ]


@pytest.mark.anyio
async def test_concurrent_refunds_reserve_the_cap_once(
    monkeypatch: pytest.MonkeyPatch, quota: RecordingQuota
) -> None:
    """The cap is reserved before the await: a refund that checks it while another
    refund is still in flight finds the cap spent."""

    # Arrange
    first_in_flight = asyncio.Event()
    second_done = asyncio.Event()

    async def slow_refund(pool: Any, *, user_id: int, day: date, cost: int) -> None:
        if not first_in_flight.is_set():
            first_in_flight.set()
            await second_done.wait()
        quota.calls.append(("refund", user_id, day, cost))

    monkeypatch.setattr(quota_module, "refund_quota", slow_refund)
    whole_cap = Charge(day=CHARGE_DAY, cost=MAX_DAILY_REFUND_UNITS)

    # Act
    first = asyncio.create_task(refund_turn(POOL, user_id=1, charge=whole_cap))
    await asyncio.wait_for(first_in_flight.wait(), timeout=1)
    await refund_turn(POOL, user_id=1, charge=Charge(day=CHARGE_DAY, cost=1))
    second_done.set()
    await first

    # Assert
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, MAX_DAILY_REFUND_UNITS)]


@pytest.mark.anyio
async def test_an_earlier_days_refunds_are_forgotten(quota: RecordingQuota) -> None:
    """A new UTC day is a new cap: the refund ledger drops the days before it."""

    # Arrange
    await refund_turn(POOL, user_id=1, charge=Charge(day=CHARGE_DAY, cost=1))

    # Act
    await refund_turn(POOL, user_id=1, charge=Charge(day=TOMORROW, cost=1))

    # Assert
    assert (1, CHARGE_DAY) not in quota_module._refunded_units
    assert quota_module._refunded_units == {(1, TOMORROW): 1}


@pytest.mark.anyio
async def test_one_users_charges_run_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user's second charge waits for the first to commit, so concurrent
    forecasts cannot each take site units before the user's own upsert."""

    # Arrange
    first_in_flight = asyncio.Event()
    release_first = asyncio.Event()
    site_calls: list[int] = []

    async def gated_site_charge(pool: Any, *, limit: int, cost: int = 1) -> int:
        site_calls.append(cost)
        if len(site_calls) == 1:
            first_in_flight.set()
            await release_first.wait()
        return cost

    monkeypatch.setattr(quota_module, "increment_site_quota", gated_site_charge)

    # Act
    first = asyncio.create_task(charge_turn(POOL, user_id=1, destination="forecast"))
    await asyncio.wait_for(first_in_flight.wait(), timeout=1)
    second = asyncio.create_task(charge_turn(POOL, user_id=1, destination="forecast"))
    for _ in range(3):
        await asyncio.sleep(0)
    waiting_site_calls = len(site_calls)
    release_first.set()
    await asyncio.gather(first, second)

    # Assert
    assert waiting_site_calls == 1
    assert len(site_calls) == 2
