import json
from typing import Any, AsyncIterator, cast
from unittest.mock import patch

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import api
from agents.orchestrator import build_graph, build_initial_orchestrator_state
from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.reporter import ResumeIntent
from agents.reporter.config import MAX_REPORT_CHARS
from agents.reporter.consts.messages import (
    CANCELLED_NOTICE,
    NO_MATERIAL_NOTICE,
    REVISION_CAP_NOTICE,
)
from agents.reporter.consts.progress import OUTLINE_PROGRESS, REPORT_PROGRESS
from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    SearchUnavailableError,
)


@pytest.fixture
def client() -> httpx.AsyncClient:
    api._rate_limit_store.clear()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://test"
    )


def _events(body: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _progress_labels(events: list[dict[str, Any]]) -> list[str]:
    return [event["label"] for event in events if event["type"] == "progress"]


@pytest.mark.anyio
async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_unknown_legacy_field_is_ignored(client: httpx.AsyncClient) -> None:
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "x", "thread_id": "t-1", "info" + "sphere": "legacy"},
        )
    assert response.status_code == 200
    assert _events(response.text)[-1]["type"] == "result"


@pytest.mark.anyio
async def test_sync_route_is_gone(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/run_pipeline", json={"query": "x", "thread_id": "t-1"}
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_stream_progress_tokens_result(client: httpx.AsyncClient) -> None:
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "Hello ")
        yield ("token", "world.")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
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

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, dict[str, str]]]:
        yield ("progress", SEARCH_PROGRESS)

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
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

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("progress", REPORT_PROGRESS)
        yield ("kind", "report")
        yield ("token", "Section one. ")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert _progress_labels(events) == ["Thinking...", "Writing the report..."]
    assert all(event.get("label") != "Writing the answer..." for event in events)
    assert events[-1]["kind"] == "report"


@pytest.mark.anyio
async def test_a_notice_is_the_answer_and_emits_no_answer_progress(
    client: httpx.AsyncClient,
) -> None:
    """A refusal or cancellation arrives whole; nothing is being written."""

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("notice", CANCELLED_NOTICE)

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
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

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("notice", notice)

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
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

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("route", "geopolitical")
        yield ("token", "hi")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["output"] == "hi"
    assert all(event["type"] != "error" for event in events)


@pytest.mark.anyio
async def test_a_pause_frame_ends_the_stream_without_a_result(
    client: httpx.AsyncClient,
) -> None:
    pause = {
        "outline": ["Section one", "Section two"],
        "notice": "",
        "revisions_used": 0,
        "revisions_allowed": 3,
    }

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        yield ("pause", pause)

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
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

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "yes", "thread_id": "t-1"}
        )
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

    monkeypatch.setattr(api, "graph", build_graph())
    assert await api._pending_pause("t-1") is None


@pytest.mark.anyio
async def test_an_approve_resume_sends_a_resume_command(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"resume": "go ahead", "thread_id": "t-1"}
        )
    assert response.status_code == 200
    assert isinstance(seen[0], Command)
    assert seen[0].resume == {"action": "approve", "instruction": ""}


@pytest.mark.anyio
async def test_a_new_question_resume_starts_a_fresh_turn(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream",
            json={"resume": "What changed on the eastern flank?", "thread_id": "t-1"},
        )
    assert response.status_code == 200
    assert not isinstance(seen[0], Command)
    assert seen[0]["messages"][-1].text() == "What changed on the eastern flank?"
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert events[-1]["kind"] == "answer"


@pytest.mark.anyio
async def test_a_query_turn_never_reads_the_checkpoint(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the resume path reads the checkpoint: an ordinary turn gains no
    new database dependency and no new failure mode."""

    async def boom(thread_id: str) -> dict[str, Any] | None:
        raise AssertionError("checkpoint read on a plain query turn")

    monkeypatch.setattr(api, "_pending_pause", boom)

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "fine")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
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
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, Any]]:
        if report_kind:
            yield ("kind", "report")
        yield ("token", "text")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert events[-1]["kind"] == expected


@pytest.mark.anyio
async def test_a_stream_of_exactly_max_answer_chars_is_not_truncated(
    client: httpx.AsyncClient,
) -> None:
    """Nothing was dropped, so nothing may be labelled partial — a `>=`
    comparison would write `report-<date>-partial.md` for a complete report."""

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "a" * (api.MAX_ANSWER_CHARS - 10))
        yield ("token", "b" * 10)

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert len(events[-1]["output"]) == api.MAX_ANSWER_CHARS
    assert events[-1]["truncated"] is False


@pytest.mark.anyio
async def test_stream_caps_answer_size(client: httpx.AsyncClient) -> None:
    fully_consumed = False

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        nonlocal fully_consumed
        yield ("token", "x" * (api.MAX_ANSWER_CHARS + 1000))
        yield ("token", "ignored after the cap")
        fully_consumed = True

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert events[-1]["type"] == "result"
    assert len(events[-1]["output"]) == api.MAX_ANSWER_CHARS
    assert events[-1]["truncated"] is True
    assert fully_consumed


@pytest.mark.anyio
async def test_rate_limit_keys_on_rightmost_forwarded(
    client: httpx.AsyncClient,
) -> None:
    """A caller cannot rotate the left-hand forwarded entry to get a fresh bucket."""

    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "answer")

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
        allowed = await client.post(
            "/api/run_pipeline/stream",
            json={"query": "different client", "thread_id": "t-1"},
            headers={"x-forwarded-for": "spoofed, 203.0.113.6"},
        )
    assert blocked.status_code == 429
    assert allowed.status_code == 200


@pytest.mark.anyio
async def test_stream_error_has_no_result(client: httpx.AsyncClient) -> None:
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        raise NoSourcesError("nothing usable")
        yield ("token", "never")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    # The thinking progress frame precedes the graph, so it survives a failure.
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["message"] == "nothing usable"


@pytest.mark.anyio
async def test_thread_id_is_required(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/run_pipeline/stream", json={"query": "x"})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_thread_id_shape_is_validated(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/run_pipeline/stream", json={"query": "x", "thread_id": "../../etc"}
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_query_validation(client: httpx.AsyncClient) -> None:
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
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        yield ("token", "output")

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
    async def stream(
        graph_input: Any, thread_id: str
    ) -> AsyncIterator[tuple[str, str]]:
        raise error
        yield ("token", "never")

    with patch("api._astream_answer", stream):
        response = await client.post(
            "/api/run_pipeline/stream", json={"query": "x", "thread_id": "t-1"}
        )
    events = _events(response.text)
    assert [event["type"] for event in events] == ["progress", "error"]
    assert events[-1]["status"] == status
    assert events[-1]["message"] == str(error)


@pytest.mark.anyio
async def test_lifespan_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "init_environment", lambda: None)
    monkeypatch.setattr(api, "init_tracing", lambda: None)
    monkeypatch.setattr(api, "require_env", lambda: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with patch("api.AsyncConnectionPool") as pool:
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            async with api.lifespan(api.app):
                pass
        pool.assert_not_called()


def test_answer_nodes_stream_write_and_never_reporter() -> None:
    """Measured: on the refusal and cancel paths the `reporter` node's
    completed AIMessage arrives in `messages` mode tagged `reporter`, and that
    same text already reaches the browser through the node's own notice event.
    Adding "reporter" here would print every refusal twice."""

    assert "write" in api.ANSWER_NODES
    assert "reporter" not in api.ANSWER_NODES


def test_search_progress_no_longer_lives_in_api() -> None:
    """The frame is emitted by `classify` and merely forwarded; the constant
    in `api.py` is dead and must not be quietly left behind."""

    assert not hasattr(api, "SEARCH_PROGRESS")


def test_report_char_cap_fits_inside_the_transport_cap() -> None:
    """The two constants are deliberately not linked by an import; if they
    diverge, the checkpointed report silently exceeds what any browser ever
    received."""

    assert MAX_REPORT_CHARS <= api.MAX_ANSWER_CHARS


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
    `AIMessage` narrowing, and `message.text()` together; every other test
    here patches it out. The geopolitical case is the regression guard for
    nested-subgraph streaming: without `subgraphs=True` it yields nothing at
    all. The report case drives the real graph with a checkpointer and
    asserts the pause event that `updates` mode carries — and, because the
    namespace guards in `test_orchestrator_graph.py` never call
    `_astream_answer`, its report case is also the only API-level guard for
    §4.18's namespace rule on either branch.
    """
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

    events = [event async for event in api._astream_answer(state, "t-1")]
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
