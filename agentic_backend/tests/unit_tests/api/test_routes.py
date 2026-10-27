from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
import pytest

from api import routes
from api.app import app
from db.web.sql import ThreadRow
from shared.config import (
    DAILY_RESEARCH_TURNS,
    FOOTER_PREFIX,
)


@pytest.mark.anyio
async def test_health(client: httpx.AsyncClient) -> None:
    # Arrange
    # Arrange
    # Act
    response = await client.get("/api/health")
    # Assert
    assert response.json() == {"status": "ok"}


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

    monkeypatch.setattr(routes, "list_threads", list_threads)
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


@pytest.mark.parametrize(
    ("path", "schema"),
    [
        ("/api/threads", "ThreadList"),
        ("/api/threads/{thread_id}", "ThreadMessages"),
        ("/api/admin/threads/{thread_id}", "ThreadMessages"),
    ],
)
def test_each_thread_route_publishes_its_response_schema(
    path: str, schema: str
) -> None:
    # Arrange
    spec = app.openapi()

    # Act
    ok = spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]

    # Assert
    assert ok["schema"]["$ref"].endswith(f"/{schema}")


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

    monkeypatch.setattr(routes, "owns_thread", deny)
    monkeypatch.setattr(routes, "_thread_messages", boom)
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

    async def messages(graph: Any, thread_id: str) -> list[dict[str, str]]:
        return [{"role": "user", "text": "hello"}]

    monkeypatch.setattr(routes, "owns_thread", own)
    monkeypatch.setattr(routes, "_thread_messages", messages)
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

    monkeypatch.setattr(routes, "is_staff", not_staff)
    monkeypatch.setattr(routes, "_thread_messages", boom)
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

    async def messages(graph: Any, thread_id: str) -> list[dict[str, str]]:
        return [{"role": "assistant", "text": "The answer."}]

    monkeypatch.setattr(routes, "is_staff", staff)
    monkeypatch.setattr(routes, "_thread_messages", messages)
    # Act
    response = await client.get("/api/admin/threads/t-1")
    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "t-1",
        "messages": [{"role": "assistant", "text": "The answer."}],
    }


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

    monkeypatch.setattr(routes, "list_threads", list_threads)
    monkeypatch.setattr(routes, "quota_used", quota_used)
    # Act
    response = await client.get("/api/threads")
    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "threads": [],
        "quota": {"used": 3, "limit": DAILY_RESEARCH_TURNS},
    }


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


def _tool_call(name: str = "run_expert") -> Any:
    from langchain_core.messages import AIMessage

    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "tc-1"}])


def _tool_result(artifact: Any = None, content: str = "Summary.") -> Any:
    from langchain_core.messages import ToolMessage

    return ToolMessage(content=content, tool_call_id="tc-1", artifact=artifact)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("build_messages", "expected"),
    [
        pytest.param(
            lambda: [
                _human("Oil?"),
                _tool_call(),
                _tool_result({"text": "Oil analysis."}),
                _ai(f"{FOOTER_PREFIX}1. Deep dive"),
            ],
            [
                {"role": "user", "text": "Oil?"},
                {
                    "role": "assistant",
                    "text": f"Oil analysis.{FOOTER_PREFIX}1. Deep dive",
                },
            ],
            id="research-turn-with-footer",
        ),
        pytest.param(
            lambda: [
                _human("Report?"),
                _tool_call("run_reporter"),
                _tool_result({"text": "# Report"}),
            ],
            [
                {"role": "user", "text": "Report?"},
                {"role": "assistant", "text": "# Report"},
            ],
            id="report-turn-has-no-footer",
        ),
        pytest.param(
            lambda: [_human("Hi"), _ai("Hello!")],
            [{"role": "user", "text": "Hi"}, {"role": "assistant", "text": "Hello!"}],
            id="chat-turn",
        ),
        pytest.param(
            lambda: [_human("Q"), _tool_call(), _tool_result(None, "Plain content.")],
            [
                {"role": "user", "text": "Q"},
                {"role": "assistant", "text": "Plain content."},
            ],
            id="tool-message-without-artifact",
        ),
        pytest.param(
            lambda: [
                _human("Q"),
                _tool_call(),
                _tool_result({"other": 1}, "Fallback."),
            ],
            [{"role": "user", "text": "Q"}, {"role": "assistant", "text": "Fallback."}],
            id="artifact-without-text",
        ),
        pytest.param(
            lambda: [
                _human("A"),
                _tool_call(),
                _tool_result({"text": "First."}),
                _ai(f"{FOOTER_PREFIX}one"),
                _human("B"),
                _tool_call(),
                _tool_result({"text": "Second."}),
                _ai(f"{FOOTER_PREFIX}two"),
            ],
            [
                {"role": "user", "text": "A"},
                {"role": "assistant", "text": f"First.{FOOTER_PREFIX}one"},
                {"role": "user", "text": "B"},
                {"role": "assistant", "text": f"Second.{FOOTER_PREFIX}two"},
            ],
            id="two-turns-in-a-row",
        ),
        pytest.param(
            lambda: [_human("Q"), _tool_call()],
            [{"role": "user", "text": "Q"}],
            id="paused-tool-call-renders-nothing",
        ),
    ],
)
async def test_thread_messages_renders_each_message_shape(
    monkeypatch: pytest.MonkeyPatch,
    build_messages: Callable[[], list[Any]],
    expected: list[dict[str, str]],
) -> None:
    # Arrange
    class _FakeSnapshot:
        values = {"messages": build_messages()}

    class _FakeCheckpointerGraph:
        checkpointer = object()

        async def aget_state(self, config: Any) -> Any:
            return _FakeSnapshot()

    # Act
    rendered = await routes._thread_messages(_FakeCheckpointerGraph(), "t-history-1")

    # Assert
    assert [message.model_dump() for message in rendered] == expected


def _human(text: str) -> Any:
    from langchain_core.messages import HumanMessage

    return HumanMessage(text)


def _ai(text: str) -> Any:
    from langchain_core.messages import AIMessage

    return AIMessage(text)
