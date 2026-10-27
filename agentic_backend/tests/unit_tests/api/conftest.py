import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator

import httpx
import jwt
import pytest

from api import quota as quota_module
from api import rate_limit, routes, stream
from api.app import app
from models import OutlinePause

CHARGE_DAY = date(2026, 10, 16)


def _mint_token(user_id: int, *, expired: bool = False) -> str:
    """Mint a test token with simplejwt's documented claim shape."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=-1 if expired else 15)
    return jwt.encode(
        {"user_id": str(user_id), "token_type": "access", "exp": exp, "jti": "t"},
        os.environ["JWT_SIGNING_KEY"],
        algorithm="HS256",
    )


def _client_with_token(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture
def client() -> httpx.AsyncClient:
    rate_limit._rate_limit_store.clear()
    quota_module._refunded_units.clear()
    app.state.pool = None  # every test patches the threads helpers it needs
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {_mint_token(user_id=1)}"},
    )


@pytest.fixture(autouse=True)
def _owned_thread_with_quota_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    """A turn whose thread is claimed and whose quota has headroom, unless a
    test says otherwise."""

    async def claim(*args: Any, **kwargs: Any) -> bool:
        return True

    async def headroom(pool: Any, *, user_id: int) -> int:
        return 0

    monkeypatch.setattr(stream, "claim_thread", claim)
    monkeypatch.setattr(routes, "quota_used", headroom)
    monkeypatch.setattr(quota_module, "quota_used", headroom)

    async def own(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(routes, "owns_thread", own)
    monkeypatch.setattr(stream, "owns_thread", own)


@dataclass
class RecordingQuota:
    """Stands in for the quota writes and records every call in order.

    `user_has_room` and `site_has_room` set to False refuse the matching
    increment, as the conditional upsert does at its cap.
    """

    user_has_room: bool = True
    site_has_room: bool = True
    refund_error: BaseException | None = None
    calls: list[tuple[Any, ...]] = field(default_factory=list)

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

    def charged(self) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == "user"]

    def refunds(self) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == "refund"]

    def site_calls(self) -> list[tuple[Any, ...]]:
        return [call for call in self.calls if call[0] == "site"]


@pytest.fixture(autouse=True)
def quota(monkeypatch: pytest.MonkeyPatch) -> RecordingQuota:
    """Every turn has room on both counters and today is CHARGE_DAY, unless a
    test says otherwise."""
    recording = RecordingQuota()
    monkeypatch.setattr(quota_module, "increment_quota", recording.increment_quota)
    monkeypatch.setattr(
        quota_module, "increment_site_quota", recording.increment_site_quota
    )
    monkeypatch.setattr(quota_module, "refund_quota", recording.refund_quota)
    monkeypatch.setattr(quota_module, "quota_day", lambda: CHARGE_DAY)
    return recording


def _events(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _turn_stream(
    destination: Any, *events: stream.StreamEvent, error: BaseException | None = None
) -> Callable[[Any, Any, str], AsyncIterator[stream.StreamEvent]]:
    """Build a fake `_astream_answer` for one turn: the counted frame, then
    the case's events or a raise."""

    async def turn(
        graph: Any, graph_input: Any, thread_id: str
    ) -> AsyncIterator[stream.StreamEvent]:
        yield stream._Counted(destination=destination)
        for event in events:
            yield event
        if error is not None:
            raise error

    return turn


def _progress_labels(events: list[dict[str, Any]]) -> list[str]:
    return [event["label"] for event in events if event["type"] == "progress"]


def _pending_pause_stub(graph: Any, thread_id: str) -> OutlinePause:
    """The pause frame `_turn_input` must find for a resume to proceed."""
    return OutlinePause(
        outline=["Section one"], notice="", revisions_used=0, revisions_allowed=3
    )


async def _pending_pause_async(graph: Any, thread_id: str) -> OutlinePause:
    return _pending_pause_stub(graph, thread_id)
