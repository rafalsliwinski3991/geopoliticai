import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator, cast
from unittest.mock import patch

import httpx
import jwt
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from psycopg.errors import OperationalError

import api
import auth
import quota as quota_module
from agents.orchestrator import build_graph, build_initial_orchestrator_state
from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.reporter import ResumeIntent
from agents.reporter.consts.messages import (
    CANCELLED_NOTICE,
    NO_MATERIAL_NOTICE,
    REVISION_CAP_NOTICE,
)
from agents.reporter.consts.progress import OUTLINE_PROGRESS, REPORT_PROGRESS
from config import (
    DAILY_RESEARCH_TURNS,
    DAILY_RESEARCH_TURNS_ALL_USERS,
    DEEP_RESEARCH_TURN_COST,
    FORECAST_TURN_COST,
    MAX_DAILY_REFUND_UNITS,
    LogContextFilter,
)
from db.web.sql import ThreadRow
from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    ResearchLimitError,
    SearchUnavailableError,
    Source,
)

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
        transport=httpx.ASGITransport(app=api.app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture
def client() -> httpx.AsyncClient:
    api._rate_limit_store.clear()
    quota_module._refunded_units.clear()
    api.app.state.pool = None  # every test patches the threads helpers it needs
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app),
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

    monkeypatch.setattr(api, "claim_thread", claim)
    monkeypatch.setattr(api, "quota_used", headroom)
    monkeypatch.setattr(quota_module, "quota_used", headroom)

    async def own(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(api, "owns_thread", own)


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
    destination: Any, *events: tuple[str, Any], error: BaseException | None = None
) -> Callable[[Any, str], AsyncIterator[tuple[str, Any]]]:
    """Build a fake `_astream_answer` for one turn: the counted frame, then
    the case's events or a raise."""

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", destination)
        for event in events:
            yield event
        if error is not None:
            raise error

    return stream


def _progress_labels(events: list[dict[str, Any]]) -> list[str]:
    return [event["label"] for event in events if event["type"] == "progress"]


def _pending_pause_stub(thread_id: str) -> dict[str, Any]:
    """The pause frame `_turn_input` must find for a resume to proceed."""
    return {"outline": ["Section one"], "revisions_used": 0, "revisions_allowed": 3}


async def _pending_pause_async(thread_id: str) -> dict[str, Any]:
    return _pending_pause_stub(thread_id)


def _owning_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    async def own(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(api, "owns_thread", own)


@pytest.mark.anyio
async def test_health(client: httpx.AsyncClient) -> None:
    # Arrange
    # Arrange
    # Act
    response = await client.get("/api/health")
    # Assert
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_unknown_legacy_field_is_ignored(client: httpx.AsyncClient) -> None:
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        # Arrange
        yield ("token", "answer")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x", "thread_id": "t-1", "info" + "sphere": "legacy"},
        )
    # Assert
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"


@pytest.mark.anyio
async def test_sync_route_is_gone(client: httpx.AsyncClient) -> None:
    # Arrange
    # Arrange
    # Act
    response = await client.post(
        "/api/run_pipeline", json={"query": "x", "thread_id": "t-1"}
    )
    # Assert
    assert response.status_code == 404


@pytest.mark.anyio
async def test_stream_progress_tokens_result(client: httpx.AsyncClient) -> None:
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        # Arrange
        yield ("token", "Hello ")
        yield ("token", "world.")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert [event["type"] for event in events] == [
        "progress",
        "progress",
        "token",
        "token",
        "result",
    ]
    assert _progress_labels(events) == [
        "Thinking...",
        "Writing the answer...",
    ]
    assert all(
        event.get("label") != "Searching and reading sources..." for event in events
    )
    assert events[-1]["output"] == "Hello world."
    assert events[-1]["kind"] == "answer"
    assert events[-1]["truncated"] is False


@pytest.mark.anyio
async def test_forwarded_progress_reaches_the_browser_verbatim(
    client: httpx.AsyncClient,
) -> None:
    """A node's progress payload is forwarded as the SSE frame itself.

    Replaces `test_expert_route_emits_the_search_frame`: the "Searching and
    reading sources..." frame is now emitted by `classify` through its writer
    and must arrive key for key, with nothing re-wrapped by `_generate`.
    """

    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        yield ("progress", SEARCH_PROGRESS)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert _progress_labels(events) == [
        "Thinking...",
        "Searching and reading sources...",
    ]
    assert events[1] == {
        "type": "progress",
        "node": "search_and_fetch",
        "label": "Searching and reading sources...",
    }


@pytest.mark.anyio
async def test_a_report_emits_no_answer_progress(client: httpx.AsyncClient) -> None:
    """The report path announces itself from `write`; "Writing the answer..."
    must not follow it, because `progressLog` never dedupes."""

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        # Arrange
        yield ("progress", REPORT_PROGRESS)
        yield ("kind", "report")
        yield ("token", "Section one. ")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert _progress_labels(events) == ["Thinking...", "Writing the report..."]
    assert all(event.get("label") != "Writing the answer..." for event in events)
    assert events[-1]["kind"] == "report"


@pytest.mark.anyio
async def test_a_notice_is_the_answer_and_emits_no_answer_progress(
    client: httpx.AsyncClient,
) -> None:
    """A refusal or cancellation arrives whole; nothing is being written."""

    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("notice", CANCELLED_NOTICE)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert _progress_labels(events) == ["Thinking..."]
    assert events[-1]["type"] == "result"
    assert events[-1]["output"] == CANCELLED_NOTICE
    assert events[-1]["kind"] == "answer"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "notice", [NO_MATERIAL_NOTICE, CANCELLED_NOTICE, REVISION_CAP_NOTICE]
)
async def test_cancel_and_revision_cap_resumes_end_as_answers(
    client: httpx.AsyncClient, notice: str
) -> None:
    """Neither notice ever reaches `write`, so neither may be a report — a
    report label puts a Download .md button on the cancellation text."""

    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("notice", notice)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["kind"] == "answer"
    assert events[-1]["output"] == notice


@pytest.mark.anyio
async def test_an_unknown_event_kind_is_ignored(client: httpx.AsyncClient) -> None:
    """An event kind this layer does not know is dropped, not appended.

    Without the guard, `value[:remaining]` on a non-string kills the turn with
    a TypeError inside the SSE generator and the client sees a truncated
    stream with no error frame at all.
    """

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        # Arrange
        yield ("route", "geopolitical")
        yield ("token", "hi")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["output"] == "hi"
    assert all(event["type"] != "error" for event in events)


@pytest.mark.anyio
async def test_a_pause_frame_ends_the_stream_without_a_result(
    client: httpx.AsyncClient,
) -> None:
    # Arrange
    pause = {
        "outline": ["Section one", "Section two"],
        "notice": "",
        "revisions_used": 0,
        "revisions_allowed": 3,
    }

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("pause", pause)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert [event["type"] for event in events] == ["progress", "pause"]
    assert set(events[-1]) == {
        "type",
        "outline",
        "notice",
        "revisions_used",
        "revisions_allowed",
    }
    assert "kind" not in events[-1]
    assert events[-1]["outline"] == pause["outline"]


@pytest.mark.anyio
async def test_resume_with_no_pending_pause_is_a_409_error_frame(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 409 arrives as an SSE error frame on an HTTP 200: a checkpoint read
    must not be able to change the committed status for any branch."""

    # Arrange
    # Arrange
    async def no_pause(thread_id: str) -> dict[str, Any] | None:
        return None

    async def intent(text: str, pause: dict[str, Any]) -> ResumeIntent:
        raise AssertionError("classify_resume_intent must not run without a pause")

    monkeypatch.setattr(api, "_pending_pause", no_pause)
    monkeypatch.setattr(api, "classify_resume_intent", intent)

    called = False

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        nonlocal called
        called = True
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "yes", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    events = _events(response.text)
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["status"] == 409
    assert not called


@pytest.mark.anyio
async def test_pending_pause_returns_none_without_a_checkpointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real `_pending_pause` answers None for a checkpointer-less graph.

    A graph with no checkpointer — `build_graph()` under `make test` and
    `langgraph dev` — cannot hold a pause at all, so None is the true answer,
    not a fallback. If the `checkpointer` guard ever regressed, `aget_state`
    would raise `ValueError("No checkpointer set")` and a stale resume would
    surface as a 500 instead of the intended 409.
    """

    # Arrange
    # Arrange
    monkeypatch.setattr(api, "graph", build_graph())
    # Act
    # Assert
    assert await api._pending_pause("t-1") is None


@pytest.mark.anyio
async def test_an_approve_resume_sends_a_resume_command(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def pending(thread_id: str) -> dict[str, Any] | None:
        return {
            "outline": ["Section one"],
            "notice": "",
            "revisions_used": 1,
            "revisions_allowed": 3,
        }

    async def intent(text: str, pause: dict[str, Any]) -> ResumeIntent:
        return ResumeIntent(action="approve", instruction="")

    monkeypatch.setattr(api, "_pending_pause", pending)
    monkeypatch.setattr(api, "classify_resume_intent", intent)

    seen: list[Any] = []

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        seen.append(graph_input)
        yield ("token", "The report.")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "go ahead", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    assert isinstance(seen[0], Command)
    assert seen[0].resume == {"action": "approve", "instruction": ""}


@pytest.mark.anyio
async def test_an_approve_resume_proceeds_at_the_cap(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, quota: RecordingQuota
) -> None:
    """Approving a pending report is free: the quota must never strand it."""

    # Arrange
    # Arrange
    async def pending(thread_id: str) -> dict[str, Any] | None:
        return {
            "outline": ["Section one"],
            "notice": "",
            "revisions_used": 1,
            "revisions_allowed": 3,
        }

    async def intent(text: str, pause: dict[str, Any]) -> ResumeIntent:
        return ResumeIntent(action="approve", instruction="")

    async def exhausted(pool: Any, *, user_id: int) -> int:
        return DAILY_RESEARCH_TURNS

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "The report.")

    monkeypatch.setattr(api, "_pending_pause", pending)
    monkeypatch.setattr(api, "classify_resume_intent", intent)
    monkeypatch.setattr(quota_module, "quota_used", exhausted)
    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "go ahead", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"
    assert quota.calls == []


@pytest.mark.anyio
async def test_a_new_question_resume_starts_a_fresh_turn(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def pending(thread_id: str) -> dict[str, Any] | None:
        return {
            "outline": ["Section one"],
            "notice": "",
            "revisions_used": 1,
            "revisions_allowed": 3,
        }

    async def intent(text: str, pause: dict[str, Any]) -> ResumeIntent:
        return ResumeIntent(action="new_question", instruction="")

    monkeypatch.setattr(api, "_pending_pause", pending)
    monkeypatch.setattr(api, "classify_resume_intent", intent)

    seen: list[Any] = []

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        seen.append(graph_input)
        yield ("token", "A fresh answer.")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"resume": "What changed on the eastern flank?", "thread_id": "t-1"},
        )
    # Assert
    assert response.status_code == 200
    assert not isinstance(seen[0], Command)
    assert seen[0]["messages"][-1].text == "What changed on the eastern flank?"
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["kind"] == "answer"


@pytest.mark.anyio
async def test_a_query_turn_never_reads_the_checkpoint(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the resume path reads the checkpoint: an ordinary turn gains no
    new database dependency and no new failure mode."""

    # Arrange
    # Arrange
    async def boom(thread_id: str) -> dict[str, Any] | None:
        raise AssertionError("checkpoint read on a plain query turn")

    monkeypatch.setattr(api, "_pending_pause", boom)

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "fine")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["output"] == "fine"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("report_kind", "expected"), [(True, "report"), (False, "answer")]
)
async def test_result_kind_is_stamped_from_the_write_node(
    client: httpx.AsyncClient, report_kind: bool, expected: str
) -> None:
    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        if report_kind:
            yield ("kind", "report")
        yield ("token", "text")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["kind"] == expected


@pytest.mark.anyio
async def test_a_stream_of_exactly_max_answer_chars_is_not_truncated(
    client: httpx.AsyncClient,
) -> None:
    """Nothing was dropped, so nothing may be labelled partial — a `>=`
    comparison would write `report-<date>-partial.md` for a complete report."""

    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "a" * (api.MAX_ANSWER_CHARS - 10))
        yield ("token", "b" * 10)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert len(events[-1]["output"]) == api.MAX_ANSWER_CHARS
    assert events[-1]["truncated"] is False


@pytest.mark.anyio
async def test_stream_caps_answer_size(client: httpx.AsyncClient) -> None:
    # Arrange
    fully_consumed = False

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        # Arrange
        nonlocal fully_consumed
        yield ("token", "x" * (api.MAX_ANSWER_CHARS + 1000))
        yield ("token", "ignored after the cap")
        fully_consumed = True

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert len(events[-1]["output"]) == api.MAX_ANSWER_CHARS
    assert events[-1]["truncated"] is True
    assert fully_consumed


@pytest.mark.anyio
async def test_rate_limit_keys_on_the_authenticated_user(
    client: httpx.AsyncClient,
) -> None:
    """A signed-in caller cannot rotate X-Forwarded-For to get a fresh bucket (Q17)."""

    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    # Act
    with patch("api._astream_answer", stream):
        for index in range(api.RATE_LIMIT_REQUESTS):
            response = await client.post(
                "/api/run_pipeline/stream",
                json={"query": f"q{index}", "thread_id": "t-1"},
                headers={"x-forwarded-for": f"spoofed-{index}, 203.0.113.5"},
            )
            assert response.status_code == 200
        blocked = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "one more", "thread_id": "t-1"},
            headers={"x-forwarded-for": "another-spoof, 203.0.113.5"},
        )
        other_identity = _client_with_token(_mint_token(user_id=2))
        allowed = await other_identity.post(
            "/api/run_pipeline/stream",
            json={"query": "different client", "thread_id": "t-1"},
        )
    # Assert
    assert blocked.status_code == 429
    assert allowed.status_code == 200


def test_resolve_client_id_falls_back_to_the_rightmost_forwarded() -> None:
    """The unauthenticated fallback keeps the right-most-entry rule."""

    # Arrange
    # Arrange
    stub = cast(
        Any,
        type(
            "R",
            (),
            {"headers": {"x-forwarded-for": "a, b, 203.0.113.5"}, "client": None},
        )(),
    )
    # Act
    resolved_anonymous = api._resolve_client_id(stub)
    resolved_authenticated = api._resolve_client_id(stub, auth.Identity(user_id=7))
    # Assert
    assert resolved_anonymous == "203.0.113.5"
    assert resolved_authenticated == "user:7"
    assert api._resolve_client_id(stub, auth.Identity(user_id=7)) == "user:7"


@pytest.mark.anyio
async def test_stream_error_has_no_result(client: httpx.AsyncClient) -> None:
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        # Arrange
        raise NoSourcesError("nothing usable")
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    # The thinking progress frame precedes the graph, so it survives a failure.
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["message"] == "nothing usable"


@pytest.mark.anyio
async def test_thread_id_is_required(client: httpx.AsyncClient) -> None:
    # Arrange
    # Arrange
    # Act
    response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    # Assert
    assert response.status_code == 422


@pytest.mark.anyio
async def test_thread_id_shape_is_validated(client: httpx.AsyncClient) -> None:
    # Arrange
    # Arrange
    # Act
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "../../etc"}
    )
    # Assert
    assert response.status_code == 422


@pytest.mark.anyio
async def test_query_validation(client: httpx.AsyncClient) -> None:
    # Arrange
    # Arrange
    # Act
    # Assert
    assert (
        await client.post(
            "/api/run_pipeline/stream", json={"query": "", "thread_id": "t-1"}
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x" * 3000, "thread_id": "t-1"},
        )
    ).status_code == 422
    assert (await client.post("/api/run_pipeline/stream", json={})).status_code == 422
    assert (
        await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x", "resume": "y", "thread_id": "t-1"},
        )
    ).status_code == 422


@pytest.mark.anyio
async def test_rate_limiting_enforced(client: httpx.AsyncClient) -> None:
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        # Arrange
        yield ("token", "output")

    # Act
    with patch("api._astream_answer", stream):
        for index in range(20):
            response = await client.post(
                "/api/run_pipeline/stream",
                json={"query": f"query {index}", "thread_id": "t-1"},
            )
            assert response.status_code == 200
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "query 21", "thread_id": "t-1"},
        )
    # Assert
    assert response.status_code == 429


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NoSourcesError("none"), 422),
        (SearchUnavailableError("down"), 503),
        (LLMInvocationError("bad"), 502),
    ],
)
async def test_stream_reports_error_status_per_type(
    client: httpx.AsyncClient, error: PipelineError, status: int
) -> None:
    # Arrange
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        raise error
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["status"] == status
    assert events[-1]["message"] == str(error)


@pytest.mark.anyio
async def test_lifespan_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    # Arrange
    monkeypatch.setattr(api, "init_environment", lambda: None)
    monkeypatch.setattr(api, "init_tracing", lambda: None)
    monkeypatch.setattr(api, "require_env", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Act
    with patch("api.AsyncConnectionPool") as pool:
        # Assert
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            async with api.lifespan(api.app):
                pass
        pool.assert_not_called()


def test_answer_nodes_stream_write_and_never_reporter() -> None:
    """Measured: on the refusal and cancel paths the `reporter` node's
    completed AIMessage arrives in `messages` mode tagged `reporter`, and that
    same text already reaches the browser through the node's own notice event.
    Adding "reporter" here would print every refusal twice."""

    # Assert
    assert "write" in api.ANSWER_NODES
    assert "reporter" not in api.ANSWER_NODES


def test_search_progress_no_longer_lives_in_api() -> None:
    """The frame is emitted by `classify` and merely forwarded; the constant
    in `api.py` is dead and must not be quietly left behind."""

    # Assert
    assert not hasattr(api, "SEARCH_PROGRESS")


@pytest.mark.parametrize(
    ("destination", "expected"),
    [("geopolitical", "Hello world."), ("other", "Hello world."), ("report", "")],
)
@pytest.mark.anyio
async def test_astream_answer_streams_the_answer_of_either_branch(
    monkeypatch: pytest.MonkeyPatch, destination: str, expected: str
) -> None:
    """The one test that actually executes `_astream_answer`.

    Covers `subgraphs=True`, the three-tuple unpacking, the custom-mode
    forwarding, the `langgraph_node` filter across the answer nodes, the
    `AIMessage` narrowing, and `message.text` together; every other test
    here patches it out. The geopolitical case is the regression guard for
    nested-subgraph streaming: without `subgraphs=True` it yields nothing at
    all. The report case drives the real graph with a checkpointer and
    asserts the pause event that `updates` mode carries — and, because the
    namespace guards in `test_orchestrator_graph.py` never call
    `_astream_answer`, its report case is also the only API-level guard for
    §4.18's namespace rule on either branch.
    """
    # Arrange
    # Arrange
    import importlib

    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.messages import AIMessage

    from agents.orchestrator.state import Destination, RouteDecision
    from agents.reporter.state import OutlineDraft
    from models import Candidate, Source

    search_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
    classify_module = importlib.import_module("agents.orchestrator.nodes.classify")
    outline_module = importlib.import_module("agents.reporter.nodes.outline")
    llm_module = importlib.import_module("llm")
    graph_module = importlib.import_module("agents.orchestrator.graph")

    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("title", "https://reuters.com/x", "reuters.com")]

    async def sources(items: list[Candidate], policy: Any) -> list[Source]:
        return [Source("title", "https://reuters.com/x", "body")]

    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        route = cast(Destination, destination)
        return RouteDecision(destination=route, standalone_query="rewritten")

    async def draft(*args: Any, **kwargs: Any) -> OutlineDraft:
        return OutlineDraft(sections=["Section one"], notice="")

    monkeypatch.setattr(search_module, "search_allowlisted", candidates)
    monkeypatch.setattr(search_module, "fetch_sources", sources)
    monkeypatch.setattr(classify_module, "ainvoke_structured", decide)
    monkeypatch.setattr(outline_module, "ainvoke_structured", draft)
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=["Hello world."]),
    )

    state = build_initial_orchestrator_state("question")
    if destination == "report":
        # The refusal is a pure function of the thread: without a cited
        # assistant turn the orchestrator never invokes the child at all.
        state["messages"].append(AIMessage("Here it is [1](https://reuters.com/x)."))
        monkeypatch.setattr(
            api, "graph", graph_module.build_graph(checkpointer=InMemorySaver())
        )
    else:
        monkeypatch.setattr(api, "graph", graph_module.build_graph())

    # Act
    events = [event async for event in api._astream_answer(state, "t-1")]
    # Assert
    tokens = "".join(text for kind, text in events if kind == "token")
    assert tokens == expected
    if destination == "geopolitical":
        assert ("progress", SEARCH_PROGRESS) in events
    if destination == "other":
        assert [kind for kind, _ in events if kind == "progress"] == []
    if destination == "report":
        # API-level guard for §4.18's namespace rule: the raw-graph tests in
        # test_orchestrator_graph.py never call `_astream_answer`, so without
        # these two assertions a regression here would reach the browser
        # untested. Exactly one pause — the `__interrupt__` is emitted twice,
        # and only the empty-namespace copy may pass the `updates` filter —
        # and OUTLINE_PROGRESS must survive the `custom` branch, which must
        # NOT apply that filter: the frame arrives under the non-empty child
        # namespace `('reporter:<uuid>',)` and a namespace filter here drops
        # every reporter progress frame silently, with no error at all.
        pauses = [value for kind, value in events if kind == "pause"]
        assert len(pauses) == 1
        assert pauses[0]["outline"] == ["Section one"]
        assert ("progress", OUTLINE_PROGRESS) in events


@pytest.mark.anyio
async def test_stream_without_a_token_is_401_and_the_graph_is_never_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One test asserts the negative: no header, no graph, no 200."""
    # Arrange
    # Arrange
    api._rate_limit_store.clear()
    api.app.state.pool = None
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    )

    async def boom(*args: Any, **kwargs: Any) -> tuple[str, str]:
        raise AssertionError("the graph must not be reached without a token")
        return ("token", "never")

    monkeypatch.setattr(api, "claim_thread", boom)
    monkeypatch.setattr(api, "_astream_answer", boom)

    # Act
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
    )
    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_stream_with_an_expired_token_is_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    # Arrange
    api._rate_limit_store.clear()
    api.app.state.pool = None
    client = _client_with_token(_mint_token(user_id=1, expired=True))

    async def boom(*args: Any, **kwargs: Any) -> tuple[str, str]:
        raise AssertionError("the graph must not be reached with an expired token")
        return ("token", "never")

    monkeypatch.setattr(api, "claim_thread", boom)
    monkeypatch.setattr(api, "_astream_answer", boom)

    # Act
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
    )
    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_another_users_thread_is_403_and_the_graph_is_never_invoked(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The thread ownership check runs before anything expensive happens."""

    # Arrange
    # Arrange
    async def deny(*args: Any, **kwargs: Any) -> bool:
        return False

    async def boom(*args: Any, **kwargs: Any) -> tuple[str, str]:
        raise AssertionError("the graph must not run for someone else's thread")
        return ("token", "never")

    monkeypatch.setattr(api, "claim_thread", deny)
    monkeypatch.setattr(api, "_astream_answer", boom)

    # Act
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
    )
    # Assert
    assert response.status_code == 403


@pytest.mark.anyio
async def test_a_resume_never_upserts_and_never_mints_a_thread(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume verifies ownership only; a fresh thread it can never create.

    Upserting on the resume path minted a blank-titled `chat_threads` row for
    every stale or hand-crafted resume before the pending-report read raised
    the 409 — a ghost conversation the sidebar would keep forever.
    """

    # Arrange
    # Arrange
    async def boom(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("a resume must not create a thread")
        return True

    async def own(*args: Any, **kwargs: Any) -> bool:
        # True: the thread exists and belongs to the caller.
        return True

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    monkeypatch.setattr(api, "claim_thread", boom)
    monkeypatch.setattr(api, "owns_thread", own)
    monkeypatch.setattr(api, "_pending_pause", _pending_pause_async)

    async def approve(text: str, pause: dict[str, Any]) -> ResumeIntent:
        return ResumeIntent(action="approve", instruction="")

    monkeypatch.setattr(api, "classify_resume_intent", approve)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "go ahead", "thread_id": "t-1"}
        )

    # Assert
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"


@pytest.mark.anyio
async def test_a_resume_of_an_unknown_thread_is_403_without_upserting(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No upsert means an unknown thread cannot be created by a resume."""

    # Arrange
    # Arrange
    async def boom(*args: Any, **kwargs: Any) -> bool:
        raise AssertionError("a resume must not create a thread")
        return True

    async def no_thread(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(api, "claim_thread", boom)
    monkeypatch.setattr(api, "owns_thread", no_thread)

    # Act
    response = await client.post(
        "/api/run_pipeline/stream", json={"resume": "go ahead", "thread_id": "t-404"}
    )

    # Assert
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_threads_returns_only_the_callers_rows(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    seen_kwargs: dict[str, Any] = {}

    async def list_threads(pool: Any, *, user_id: int) -> list[ThreadRow]:
        seen_kwargs["user_id"] = user_id
        return [
            ThreadRow(
                id="t1",
                title="NATO",
                created_at=datetime.fromisoformat("2026-09-18T10:00:00Z"),
            ),
        ]

    monkeypatch.setattr(api, "list_threads", list_threads)
    # Act
    response = await client.get("/api/threads")
    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "threads": [
            {"id": "t1", "title": "NATO", "created_at": "2026-09-18T10:00:00Z"}
        ],
        "quota": {"used": 0, "limit": DAILY_RESEARCH_TURNS},
    }
    assert seen_kwargs["user_id"] == 1


@pytest.mark.anyio
async def test_get_thread_403_for_a_thread_the_caller_does_not_own(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def deny(*args: Any, **kwargs: Any) -> bool:
        return False

    async def boom(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
        raise AssertionError("the checkpoint must not be read for a foreign thread")
        return []

    monkeypatch.setattr(api, "owns_thread", deny)
    monkeypatch.setattr(api, "_thread_messages", boom)
    # Act
    response = await client.get("/api/threads/t-1")
    # Assert
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_thread_returns_the_callers_messages(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def own(*args: Any, **kwargs: Any) -> bool:
        return True

    async def messages(thread_id: str) -> list[dict[str, str]]:
        return [{"role": "user", "text": "hello"}]

    monkeypatch.setattr(api, "owns_thread", own)
    monkeypatch.setattr(api, "_thread_messages", messages)
    # Act
    response = await client.get("/api/threads/t-1")
    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "t-1",
        "messages": [{"role": "user", "text": "hello"}],
    }


@pytest.mark.anyio
async def test_admin_thread_endpoint_with_is_staff_false_is_403(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def not_staff(*args: Any, **kwargs: Any) -> bool:
        return False

    async def boom(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
        raise AssertionError("staff check must gate the checkpoint read")
        return []

    monkeypatch.setattr(api, "is_staff", not_staff)
    monkeypatch.setattr(api, "_thread_messages", boom)
    # Act
    response = await client.get("/api/admin/threads/t-1")
    # Assert
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_thread_endpoint_with_is_staff_true_returns_messages(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def staff(*args: Any, **kwargs: Any) -> bool:
        return True

    async def messages(thread_id: str) -> list[dict[str, str]]:
        return [{"role": "assistant", "text": "The answer."}]

    monkeypatch.setattr(api, "is_staff", staff)
    monkeypatch.setattr(api, "_thread_messages", messages)
    # Act
    response = await client.get("/api/admin/threads/t-1")
    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "t-1",
        "messages": [{"role": "assistant", "text": "The answer."}],
    }


@pytest.mark.anyio
async def test_the_21st_research_turn_is_429_mid_stream(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """The cap is enforced in the counted branch: a research turn over it is
    refused with a 429 error frame on an HTTP 200, never a result."""

    # Arrange
    # The caller's own cap is the one already reached; the site still has
    # headroom for the refusal (the autouse `quota` fixture).
    quota.user_has_room = False

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", None)
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 429
    assert all(event["type"] != "result" for event in events)


@pytest.mark.anyio
async def test_a_chat_routed_turn_proceeds_at_the_cap(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, quota: RecordingQuota
) -> None:
    """Chat is free (Q5b): an exhausted user may still chat, and the counted
    branch — the only place a turn is refused — never fires."""

    # Arrange
    # Arrange
    async def exhausted(pool: Any, *, user_id: int) -> int:
        return DAILY_RESEARCH_TURNS

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "Hello.")

    monkeypatch.setattr(quota_module, "quota_used", exhausted)
    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "chat please", "thread_id": "t-1"},
        )
    # Assert
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"
    assert quota.calls == []


@pytest.mark.anyio
async def test_a_turn_refused_by_the_site_ceiling_does_not_charge_the_user(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """The site increment commits before the user's: a turn the site refuses
    costs the caller nothing, with no advisory read that a race could open."""

    # Arrange
    # The site is already at its ceiling; the caller still has headroom.
    quota.site_has_room = False

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", None)
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 429
    assert events[-1]["message"] == "The site has used today's research capacity."
    assert all(event["type"] != "result" for event in events)
    assert quota.charged() == []


@pytest.mark.anyio
async def test_a_chat_routed_turn_does_not_increment_the_quota(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """`other` is not a research destination; the increment never fires."""

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "Hello.")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "chat please", "thread_id": "t-1"},
        )
    # Assert
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"
    assert quota.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("destination", ["geopolitical", "report"])
async def test_a_research_routed_turn_increments_exactly_once(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    quota: RecordingQuota,
    destination: str,
) -> None:
    """Counting rides the `classify` updates frame, once, in _generate.

    This test fails against a `_generate` that never grew the `counted`
    branch, which is the whole point: implementing only the _astream_answer
    half ships an unlimited quota with a green suite.
    """
    # Arrange
    # Arrange
    from langchain_core.messages import AIMessage

    classify_update = {
        "classify": {"destination": destination, "standalone_query": "q"}
    }
    seen_inputs: list[Any] = []

    class _FakeGraph:
        async def astream(
            self, graph_input: Any, config: Any, **kwargs: Any
        ) -> AsyncIterator[tuple[Any, str, Any]]:
            seen_inputs.append(graph_input)
            # updates mode, empty namespace first — as langgraph delivers it
            yield ("", "updates", classify_update)
            # the answer arrives via messages mode
            yield (
                ("",),
                "messages",
                (AIMessage("Answer."), {"langgraph_node": "chat"}),
            )

    monkeypatch.setattr(api, "graph", _FakeGraph())

    # Act
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
    )
    # Assert
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    # The site entry comes first: a turn the site refuses costs the user nothing.
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1),
    ]


@pytest.mark.anyio
async def test_a_turn_that_fails_after_routing_still_increments_once(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """The charge happened once when routing counted the turn, and the error
    frame gives its unit back to the charge day: a failed turn must not eat
    the user's units."""

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", None)
        raise NoSourcesError("down")
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert quota.charged() == [("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1)]
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, 1)]


@pytest.mark.anyio
async def test_a_turn_at_the_cap_ends_with_a_429_error_frame(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """A concurrent turn took the last one before this turn's increment."""

    # Arrange
    quota.user_has_room = False

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", None)
        yield ("token", "free answer")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 429
    assert all(event["type"] != "result" for event in events)


@pytest.mark.anyio
async def test_get_threads_reports_the_quota_block(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    async def list_threads(pool: Any, *, user_id: int) -> list[ThreadRow]:
        return []

    async def quota_used(pool: Any, *, user_id: int) -> int:
        return 3

    monkeypatch.setattr(api, "list_threads", list_threads)
    monkeypatch.setattr(api, "quota_used", quota_used)
    # Act
    response = await client.get("/api/threads")
    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "threads": [],
        "quota": {"used": 3, "limit": DAILY_RESEARCH_TURNS},
    }


@pytest.mark.anyio
async def test_a_client_that_disconnects_mid_stream_is_still_counted(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """The count lands at the classify frame, before any token is spent.

    Counting on the `expert` or `reporter` frame passes every other test here
    and still leaves the quota bypassable by hanging up once tokens start:
    abort the fetch mid-answer and the turn was free. This test pins the
    counting to the earliest frame.
    """

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", None)
        yield ("token", "partial answer")
        # (in production the run continues long past the first token)

    # Act
    with patch("api._astream_answer", stream):
        async with client.stream(
            "POST", "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        ) as response:
            # Read only until tokens reach the browser, then hang up: the
            # result never arrives, and the turn is still paid for.
            async for line in response.aiter_lines():
                if line.startswith("data: ") and '"token"' in line:
                    break
    # Assert
    assert quota.charged() == [("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1)]
    assert quota.refunds() == []


@pytest.mark.anyio
async def test_a_cancelled_response_is_still_counted(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """A response abandoned mid-run is still counted, and refunds nothing.

    `ASGITransport` only hands the body back once the app has finished, so
    breaking out of `aiter_lines` above reads a finished buffer. The disconnect
    a browser really causes is the cancellation of the app's task while the
    run is still streaming — and that cancellation gives no units back.
    """

    # Arrange — the run signals past the counted frame, then hangs until the
    # cancellation reaches it.
    past_the_count = asyncio.Event()

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", None)
        yield ("token", "partial answer")
        past_the_count.set()
        await asyncio.Event().wait()  # never set: the run hangs until cancelled

    async def abandon() -> None:
        with patch("api._astream_answer", stream):
            async with client.stream(
                "POST",
                "/api/run_pipeline/stream",
                json={"query": "x", "thread_id": "t-1"},
            ):
                pass  # the body never completes; the task is cancelled instead

    # Act — cancel the response while the run is still streaming.
    abandoned = asyncio.create_task(abandon())
    await past_the_count.wait()
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned

    # Assert
    assert quota.charged() == [("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1)]
    assert quota.refunds() == []


@pytest.mark.anyio
async def test_a_resume_run_counts_nothing_new(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, quota: RecordingQuota
) -> None:
    """One report is one count, taken when it was requested: classify does not
    re-run on a resume, so approving a pending outline is free."""

    # Arrange
    # Arrange
    async def pending(thread_id: str) -> dict[str, Any] | None:
        return {
            "outline": ["Section one"],
            "notice": "",
            "revisions_used": 0,
            "revisions_allowed": 3,
        }

    async def intent(text: str, pause: dict[str, Any]) -> ResumeIntent:
        return ResumeIntent(action="approve", instruction="")

    monkeypatch.setattr(api, "_pending_pause", pending)
    monkeypatch.setattr(api, "classify_resume_intent", intent)

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        # A resumed report run: the reporter continues from the interrupt; no
        # `classify` update frame ever arrives in this run.
        yield ("pause", {"outline": ["Section one"]})
        yield ("token", "The report.")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "go ahead", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"
    assert quota.calls == []


class _FakeCursor:
    """One scripted row for one execute call."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    """The single connection the guard helpers ask the pool for."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def execute(self, statement: str, params: Any = None) -> _FakeCursor:
        return _FakeCursor(self._row)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


class _FakeGuardPool:
    """Stands in for AsyncConnectionPool where the guards use it."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def connection(self) -> _FakeConn:
        return _FakeConn(self._row)

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_require_migrated_checkpointer_schema_passes_when_public_is_clean() -> (
    None
):
    # Arrange: a fresh or already-migrated database — no public.checkpoints.
    pool: Any = _FakeGuardPool({"stray": None, "target": "agentic"})
    # Act + Assert: no raise
    await api._require_migrated_checkpointer_schema(pool)  # assert: no raise


@pytest.mark.anyio
async def test_require_migrated_checkpointer_schema_refuses_a_public_target() -> None:
    # Arrange: no `agentic` schema yet, or search_path never reached the
    # connection — setup() would build its tables in `public`.
    pool: Any = _FakeGuardPool({"stray": None, "target": "public"})
    # Act
    with pytest.raises(RuntimeError, match="make migrate-agentic") as refusal:
        # Arrange
        await api._require_migrated_checkpointer_schema(pool)
    # Assert
    assert refusal.type is RuntimeError


@pytest.mark.anyio
async def test_require_migrated_checkpointer_schema_refuses_a_stray_table() -> None:
    # Arrange: the pre-migration state — public.checkpoints still exists.
    pool: Any = _FakeGuardPool({"stray": {"oid": 16384}})
    # Act
    with pytest.raises(RuntimeError, match="make migrate-agentic") as refusal:
        # Arrange
        await api._require_migrated_checkpointer_schema(pool)
    # Assert
    assert refusal.type is RuntimeError


@pytest.mark.anyio
async def test_assert_agentic_schema_passes_when_setup_created_both() -> None:
    # Arrange: both setups did their job where search_path should have put them.
    pool: Any = _FakeGuardPool({"checkpoints": {"oid": 16385}, "store": {"oid": 16386}})
    # Act + Assert: no raise
    await api._assert_agentic_schema(pool)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "row",
    [
        {"checkpoints": None, "store": {"oid": 16386}},
        {"checkpoints": {"oid": 16385}, "store": None},
    ],
    ids=["store only", "checkpointer only"],
)
async def test_assert_agentic_schema_refuses_a_missing_table(
    row: dict[str, Any],
) -> None:
    # Arrange: the pool's options did not reach the connection.
    pool: Any = _FakeGuardPool(row)
    # Act
    with pytest.raises(RuntimeError, match="search_path") as refusal:
        # Act
        # Assert: the raise is the assertion
        await api._assert_agentic_schema(pool)
    assert refusal.type is RuntimeError


@pytest.mark.anyio
async def test_lifespan_checks_the_migration_before_the_checkpointer_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordering is the entire safety property: setup() must not run while
    the checkpointer's tables are still in `public`, or it builds an empty
    second set. A refactor that reorders these calls silently restores the
    history-loss bug."""
    # Arrange
    calls: list[str] = []
    monkeypatch.setattr(api, "init_environment", lambda: None)
    monkeypatch.setattr(api, "init_tracing", lambda: None)
    monkeypatch.setattr(api, "require_env", lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql://guard:guard@127.0.0.1:5432/g")
    pool: Any = _FakeGuardPool({"stray": None})

    async def require(pool_arg: Any) -> None:
        calls.append("require")

    async def setup() -> None:
        calls.append("checkpointer_setup")

    async def assert_schema(pool_arg: Any) -> None:
        calls.append("assert_schema")

    def build_graph(checkpointer: Any, store: Any = None) -> Any:
        calls.append("graph")
        received["checkpointer"] = checkpointer
        received["store"] = store
        return object()

    monkeypatch.setattr(api, "AsyncConnectionPool", lambda *a, **k: pool)
    serdes: list[Any] = []
    received: dict[str, Any] = {}
    store_ttls: list[Any] = []

    def make_saver(pool_arg: Any, serde: Any = None) -> Any:
        serdes.append(serde)
        return type("S", (), {"setup": staticmethod(setup)})()

    def make_store(pool_arg: Any, ttl: Any = None) -> Any:
        store_ttls.append(ttl)

        class _Store:
            async def setup(self) -> None:
                calls.append("store_setup")

            async def start_ttl_sweeper(self) -> None:
                calls.append("sweeper_start")

            async def stop_ttl_sweeper(self) -> None:
                calls.append("sweeper_stop")

        return _Store()

    monkeypatch.setattr(api, "AsyncPostgresSaver", make_saver)
    monkeypatch.setattr(api, "AsyncPostgresStore", make_store)
    monkeypatch.setattr(api, "_require_migrated_checkpointer_schema", require)
    monkeypatch.setattr(api, "_assert_agentic_schema", assert_schema)
    monkeypatch.setattr(api, "build_graph", build_graph)

    # Act
    async with api.lifespan(api.app):
        # Assert (inside, so the exit paths also run)
        assert calls.index("require") < calls.index("checkpointer_setup")
        assert calls.index("checkpointer_setup") < calls.index("store_setup")
        assert calls.index("store_setup") < calls.index("assert_schema")
        assert calls.index("assert_schema") < calls.index("sweeper_start")
        assert calls.index("sweeper_start") < calls.index("graph")
        assert received["store"] is not None
        assert store_ttls == [api.STORE_TTL]
        assert serdes == [api.CHECKPOINT_SERDE]
    assert "sweeper_stop" in calls


@pytest.mark.anyio
async def test_store_ttl_is_thirty_days_from_writing() -> None:
    # Act + Assert
    assert api.STORE_TTL == {
        "default_ttl": 43_200,
        "refresh_on_read": False,
        "omit_expired": True,
        "sweep_interval_minutes": 60,
    }


@dataclass(frozen=True)
class _Stranger:
    """A custom type that is not on the checkpoint allow-list."""

    value: str


def test_checkpoint_serde_allows_source_and_blocks_other_types(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    # Arrange
    source = Source(title="T", url="https://example.org/a", text="body")
    stranger = _Stranger(value="x")

    # Act
    with caplog.at_level("DEBUG"):
        restored = api.CHECKPOINT_SERDE.loads_typed(
            api.CHECKPOINT_SERDE.dumps_typed(source)
        )
        blocked = api.CHECKPOINT_SERDE.loads_typed(
            api.CHECKPOINT_SERDE.dumps_typed(stranger)
        )

    # Assert
    assert restored == source
    assert not isinstance(blocked, _Stranger)
    assert "unregistered" not in caplog.text.lower()


@pytest.mark.anyio
async def test_unexpected_stream_failure_log_names_the_thread_and_user(
    client: httpx.AsyncClient,
) -> None:
    # Arrange
    # Arrange: a handler with the production filter, so the assertion runs on
    # the same path a real log line takes.
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect()
    handler.addFilter(LogContextFilter())
    api_logger = logging.getLogger("api")
    api_logger.addHandler(handler)

    async def boom(graph_input: Any, thread_id: str) -> AsyncIterator[tuple[str, str]]:
        raise RuntimeError("graph exploded")
        yield ("token", "never")

    # Act
    try:
        with patch("api._astream_answer", boom):
            await client.post(
                "/api/run_pipeline/stream",
                json={"query": "x", "thread_id": "thread-corr-1"},
            )
    finally:
        api_logger.removeHandler(handler)

    # Assert
    failure = next(
        r
        for r in records
        if r.getMessage() == "Streaming pipeline failed unexpectedly."
    )
    assert failure.thread_id == "thread-corr-1"  # type: ignore[attr-defined]
    assert failure.user_id == 1  # type: ignore[attr-defined]


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["/api/threads/", "/api/admin/threads/"])
@pytest.mark.parametrize("thread_id", ["t-1%0Aforged", "t%201", "a" * 101])
async def test_thread_routes_422_on_a_malformed_thread_id(
    client: httpx.AsyncClient, route: str, thread_id: str
) -> None:
    # Arrange
    # Act
    response = await client.get(route + thread_id)
    # Assert
    assert response.status_code == 422


@pytest.mark.anyio
async def test_a_geopolitical_turn_still_spends_one(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", "geopolitical")
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    assert quota.calls == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1),
        ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1),
    ]


@pytest.mark.anyio
async def test_a_geopolitical_turn_skips_the_headroom_read(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-unit turn is never refused by the headroom, so it never reads it."""

    # Arrange
    reads: list[int] = []

    async def read(pool: Any, *, user_id: int) -> int:
        reads.append(user_id)
        return 0

    monkeypatch.setattr(quota_module, "quota_used", read)

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", "geopolitical")
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    assert response.status_code == 200
    assert reads == []


@pytest.mark.anyio
async def test_a_deep_turn_reads_the_headroom_of_its_user(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A costly turn is the one the headroom read can refuse, so it reads its user's."""

    # Arrange
    reads: list[int] = []

    async def read(pool: Any, *, user_id: int) -> int:
        reads.append(user_id)
        return 0

    monkeypatch.setattr(quota_module, "quota_used", read)

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("counted", "deep")
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    assert response.status_code == 200
    assert reads == [1]


@pytest.mark.anyio
async def test_a_deep_turn_reaches_the_browser_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real graph: the deep answer arrives as one `notice`, never a token,
    and the counted event carries the destination."""

    # Arrange
    # Arrange
    import importlib

    from agents.deep_expert.consts.progress import PLANNING_PROGRESS
    from agents.orchestrator.state import RouteDecision

    classify_module = importlib.import_module("agents.orchestrator.nodes.classify")
    deep_node = importlib.import_module("agents.orchestrator.nodes.deep_expert")
    graph_module = importlib.import_module("agents.orchestrator.graph")

    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        return RouteDecision(destination="deep", standalone_query="rewritten")

    DEEP_ANSWER = "Deep answer [a](https://reuters.com/x)."

    async def fake_research(query: str, writer: Any) -> str:
        writer(PLANNING_PROGRESS)
        return DEEP_ANSWER

    monkeypatch.setattr(classify_module, "ainvoke_structured", decide)
    monkeypatch.setattr(deep_node, "research", fake_research)
    monkeypatch.setattr(api, "graph", graph_module.build_graph())

    # Act
    events = [
        event
        async for event in api._astream_answer(
            build_initial_orchestrator_state("q"), "t-1"
        )
    ]
    # Assert
    assert ("counted", "deep") in events
    assert ("progress", PLANNING_PROGRESS) in events
    assert [v for k, v in events if k == "notice"] == [DEEP_ANSWER]
    assert [v for k, v in events if k == "token"] == []


@pytest.mark.anyio
async def test_a_forecast_reaches_the_browser_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real graph: the forecast arrives as one `notice`, never a token,
    and the counted event carries the destination."""

    # Arrange
    import importlib

    from agents.orchestrator.state import RouteDecision

    classify_module = importlib.import_module("agents.orchestrator.nodes.classify")
    forecast_node = importlib.import_module("agents.orchestrator.nodes.deep_forecaster")
    graph_module = importlib.import_module("agents.orchestrator.graph")

    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        return RouteDecision(destination="forecast", standalone_query="rewritten")

    FORECAST_ANSWER = "Forecast answer [a](https://reuters.com/x)."

    async def fake_forecast(query: str, store: Any = None) -> str:
        return FORECAST_ANSWER

    monkeypatch.setattr(classify_module, "ainvoke_structured", decide)
    monkeypatch.setattr(forecast_node, "forecast", fake_forecast)
    monkeypatch.setattr(api, "graph", graph_module.build_graph())

    # Act
    events = [
        event
        async for event in api._astream_answer(
            build_initial_orchestrator_state("q"), "t-1"
        )
    ]
    # Assert
    assert ("counted", "forecast") in events
    assert [v for k, v in events if k == "notice"] == [FORECAST_ANSWER]
    assert [v for k, v in events if k == "token"] == []


@pytest.mark.anyio
async def test_no_forecaster_node_is_an_answer_node() -> None:
    # Arrange
    from agents.deep_forecaster.graph import build_graph

    # Assert
    forecaster_nodes = (
        set(build_graph().get_graph().nodes) - {"__start__", "__end__"}
    ) | {"deep_forecaster"}
    assert forecaster_nodes & api.ANSWER_NODES == set()


@pytest.mark.anyio
async def test_stream_endpoint_binds_the_trace_user(client: httpx.AsyncClient) -> None:
    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    calls: list[int] = []

    def spy(user_id: int) -> None:
        calls.append(user_id)

    # Act
    with patch("api.bind_trace_user", spy), patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    # Assert
    assert response.status_code == 200
    assert calls == [1]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NoSourcesError("no usable sources"), 422),
        (SearchUnavailableError("every search failed"), 503),
        (LLMInvocationError("the council died"), 502),
        (ResearchLimitError("the forecast ran out of time"), 504),
    ],
    ids=["no sources 422", "outage 503", "model 502", "time limit 504"],
)
async def test_a_forecast_failure_reaches_the_browser_and_refunds(
    client: httpx.AsyncClient, quota: RecordingQuota, error: PipelineError, status: int
) -> None:
    """A forecast the user paid 20 units for must not eat the charge when it
    fails: every error frame gives the units back, or a user with a
    reproducible failure (a topic with no sources) pays for every retry and
    simply stops using forecasts."""

    # Arrange — the counted forecast frame streams, then the case's error raises.
    stream = _turn_stream("forecast", error=error)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == status
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, FORECAST_TURN_COST)]
    # Site units never come back: the site ceiling is touched once, by the
    # turn's own charge, never by the refund.
    assert quota.site_calls() == [
        ("site", DAILY_RESEARCH_TURNS_ALL_USERS, FORECAST_TURN_COST)
    ]


@pytest.mark.anyio
async def test_an_unexpected_failure_gives_the_units_back(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """The generic 500 path is still an error frame: a counted turn that dies
    of a bug gives its one unit back like any other failed turn."""

    # Arrange — the counted turn streams, then dies of a bug.
    stream = _turn_stream(None, error=RuntimeError("graph exploded"))

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 500
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, 1)]
    # Site units never come back: the site ceiling is touched once, by the
    # turn's own charge, never by the refund.
    assert quota.site_calls() == [("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1)]


@pytest.mark.anyio
async def test_an_empty_answer_gives_the_units_back(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """An answer that produced no text is the 502 path: the charge is given
    back before the error frame reaches the browser."""

    # Arrange — the counted frame streams, then the stream ends with no answer.
    stream = _turn_stream(None)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 502
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, 1)]
    # Site units never come back: the site ceiling is touched once, by the
    # turn's own charge, never by the refund.
    assert quota.site_calls() == [("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "events",
    [
        [("token", "The answer.")],
        [("token", "x" * (api.MAX_ANSWER_CHARS + 1))],
        [("pause", {"outline": ["Section one"]})],
    ],
    ids=["answer", "truncated", "pause"],
)
async def test_an_answered_turn_keeps_its_charge(
    client: httpx.AsyncClient, quota: RecordingQuota, events: list[tuple[str, Any]]
) -> None:
    """Only an error frame gives units back: a turn that delivered something —
    a full answer, a long clipped-answer, or a pause the browser has the
    outline for — keeps its charge."""

    # Arrange
    stream = _turn_stream(None, *events)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    assert response.status_code == 200
    assert quota.refunds() == []
    assert quota.charged() == [("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, 1)]


@pytest.mark.anyio
async def test_a_failed_free_turn_refunds_nothing(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """Nothing was taken, so nothing is given back: a chat-path failure that
    never reached the counted branch must not even look at the counters."""

    # Arrange
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        raise NoSourcesError("down")
        yield ("token", "never")

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 422
    assert quota.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "destination", "cost"),
    [
        ("headroom", "deep", DEEP_RESEARCH_TURN_COST),
        ("headroom", "forecast", FORECAST_TURN_COST),
        ("site ceiling", "deep", DEEP_RESEARCH_TURN_COST),
        ("site ceiling", "forecast", FORECAST_TURN_COST),
        ("lost race", "deep", DEEP_RESEARCH_TURN_COST),
        ("lost race", "forecast", FORECAST_TURN_COST),
    ],
    ids=[
        "headroom deep",
        "headroom forecast",
        "site ceiling deep",
        "site ceiling forecast",
        "lost race deep",
        "lost race forecast",
    ],
)
async def test_a_refused_turn_refunds_nothing(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    quota: RecordingQuota,
    kind: str,
    destination: str,
    cost: int,
) -> None:
    """A turn refused with a 429 was never counted, so a refund would double
    the user's units: every refusal path gives nothing back."""

    # Arrange — each refusal fires before the user's own counter is charged.
    if kind == "headroom":
        # One short of affordable: the advisory pre-read refuses first.
        async def nearly_exhausted(pool: Any, *, user_id: int) -> int:
            return DAILY_RESEARCH_TURNS - cost + 1

        monkeypatch.setattr(quota_module, "quota_used", nearly_exhausted)
    elif kind == "site ceiling":
        # The caller has headroom; the site-wide ceiling is spent.
        quota.site_has_room = False
    else:  # lost race
        # The pre-read sees a fresh day; a concurrent turn wins the upsert.
        async def fresh(pool: Any, *, user_id: int) -> int:
            return 0

        monkeypatch.setattr(quota_module, "quota_used", fresh)
        quota.user_has_room = False

    stream = _turn_stream(destination)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status"] == 429
    site_charge = ("site", DAILY_RESEARCH_TURNS_ALL_USERS, cost)
    charged_turn = ("user", 1, CHARGE_DAY, DAILY_RESEARCH_TURNS, cost)
    if kind == "headroom":
        expected_calls: list[tuple[Any, ...]] = []
    elif kind == "site ceiling":
        expected_calls = [site_charge]
    else:
        expected_calls = [site_charge, charged_turn]
    assert quota.calls == expected_calls
    assert quota.refunds() == []


@pytest.mark.anyio
async def test_a_failed_refund_keeps_the_original_error(
    client: httpx.AsyncClient,
    quota: RecordingQuota,
) -> None:
    """A refund the database refuses is logged and swallowed: the user is
    about to see the turn's real error, and the refund's failure must not
    replace it."""

    # Arrange
    quota.refund_error = OperationalError("db down")
    error = NoSourcesError("no usable sources")
    stream = _turn_stream("forecast", error=error)

    # Act
    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    events = _events(response.text)
    assert events[-1] == {"type": "error", "status": 422, "message": str(error)}


@pytest.mark.anyio
async def test_the_cap_counts_units(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    quota: RecordingQuota,
) -> None:
    """The cap is measured in units, not failed turns: twenty one-unit
    failures spend it and the twenty-first gives nothing back — a cap in
    turns would have refunded twenty forecasts' worth."""

    # Arrange — the transport rate limit is not this rule's subject, and 21
    # turns inside one window would 429 before the cap could.
    monkeypatch.setattr(api, "_enforce_rate_limit", lambda *args: None)

    # Act — one failed turn at a time, twenty times, then the twenty-first.
    refunded_bodies: list[str] = []
    with patch("api._astream_answer", _turn_stream(None, error=NoSourcesError("none"))):
        for _ in range(MAX_DAILY_REFUND_UNITS):
            refunded_turn = await client.post(
                "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
            )
            refunded_bodies.append(refunded_turn.text)
        capped = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    assert [_events(body)[-1]["status"] for body in refunded_bodies] == [
        422
    ] * MAX_DAILY_REFUND_UNITS
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, 1)] * MAX_DAILY_REFUND_UNITS
    assert _events(capped.text)[-1]["status"] == 422
    # Site units never come back: each of the 21 turns is charged to the site
    # by its own charge, and no refund touches it.
    assert quota.site_calls() == [("site", DAILY_RESEARCH_TURNS_ALL_USERS, 1)] * (
        MAX_DAILY_REFUND_UNITS + 1
    )


@pytest.mark.anyio
async def test_the_cap_is_per_user(
    client: httpx.AsyncClient, quota: RecordingQuota
) -> None:
    """The cap is one user's bookkeeping: the first user spends theirs and the
    second still gets a full day's refunds."""

    # Arrange
    other = _client_with_token(_mint_token(user_id=2))

    # Act
    with patch(
        "api._astream_answer", _turn_stream("forecast", error=NoSourcesError("none"))
    ):
        at_the_cap = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
        capped = await other.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-2"}
        )

    # Assert
    assert _events(at_the_cap.text)[-1]["status"] == 422
    assert _events(capped.text)[-1]["status"] == 422
    assert quota.refunds() == [
        ("refund", 1, CHARGE_DAY, FORECAST_TURN_COST),
        ("refund", 2, CHARGE_DAY, FORECAST_TURN_COST),
    ]
    # Site units never come back: each turn charges the site ceiling itself,
    # and no refund touches it.
    assert (
        quota.site_calls()
        == [("site", DAILY_RESEARCH_TURNS_ALL_USERS, FORECAST_TURN_COST)] * 2
    )


@pytest.mark.anyio
async def test_the_cap_resets_on_the_next_day(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, quota: RecordingQuota
) -> None:
    """A new UTC day is a new cap: yesterday's refund bookkeeping is dropped,
    so the user who spent it getting one failed forecast back is whole again."""

    # Arrange — nothing refunded yet, and tomorrow's date at hand.
    tomorrow = CHARGE_DAY + timedelta(days=1)

    # Act — today's failed forecast spends the whole day's cap.
    with patch(
        "api._astream_answer", _turn_stream("forecast", error=NoSourcesError("none"))
    ):
        before_midnight = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    assert _events(before_midnight.text)[-1]["status"] == 422
    assert quota.refunds() == [("refund", 1, CHARGE_DAY, FORECAST_TURN_COST)]
    assert (1, CHARGE_DAY) in quota_module._refunded_units

    # Arrange — midnight UTC passes.
    monkeypatch.setattr(quota_module, "quota_day", lambda: tomorrow)

    # Act — the next day's first failure is refunded again.
    with patch(
        "api._astream_answer", _turn_stream("forecast", error=NoSourcesError("none"))
    ):
        after_midnight = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )

    # Assert
    assert _events(after_midnight.text)[-1]["status"] == 422
    assert quota.refunds() == [
        ("refund", 1, CHARGE_DAY, FORECAST_TURN_COST),
        ("refund", 1, tomorrow, FORECAST_TURN_COST),
    ]
    assert (1, CHARGE_DAY) not in quota_module._refunded_units
    # Site units never come back: each turn charges the site ceiling itself,
    # and no refund touches it.
    assert (
        quota.site_calls()
        == [("site", DAILY_RESEARCH_TURNS_ALL_USERS, FORECAST_TURN_COST)] * 2
    )
