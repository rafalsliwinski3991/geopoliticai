"""Unit tests for `agents.deep_expert.tools`."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from agents.deep_expert.config import LIMITS
from agents.deep_expert.state import ResearchRun
from agents.expert.consts.sources import EXPERT_SOURCES
from models import Candidate, Source
from services.code_sandbox import CodeRun
from shared.errors import SandboxUnavailableError, SearchUnavailableError
from shared.frames import ProgressFrame

tools_module: Any = __import__("importlib").import_module("agents.deep_expert.tools")

URL = "https://www.reuters.com/world/article"
# Two lines, 31 characters: the mean of twelve yearly figures.
CODE = "total = 75936\nprint(total / 12)"
DURATION_MS = 120


async def call(tool: Any, args: dict[str, Any]) -> str:
    result: str = await tool.ainvoke(args)
    return result


def tool_named(run: ResearchRun, name: str) -> Any:
    """Return this turn's one tool called `name`, so a new tool breaks no test."""
    return {tool.name: tool for tool in tools_module.build_tools(run)}[name]


class FakeSandbox:
    """Stands in for `run_code`: records each program and gives one scripted answer.

    Each answer is a run to return or an exception to raise. A call with nothing
    scripted raises, so an unexpected sandbox call fails loudly.
    """

    def __init__(self, *answers: CodeRun | Exception) -> None:
        self.answers = list(answers)
        self.codes: list[str] = []

    async def __call__(self, code: str) -> CodeRun:
        self.codes.append(code)
        if not self.answers:
            raise AssertionError("an unscripted sandbox call")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def install_sandbox(
    monkeypatch: pytest.MonkeyPatch, *answers: CodeRun | Exception
) -> FakeSandbox:
    sandbox = FakeSandbox(*answers)
    monkeypatch.setattr(tools_module, "run_code", sandbox)
    return sandbox


def finished_run(
    outcome: str = "ok",
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    truncated: bool = False,
) -> CodeRun:
    return CodeRun(
        outcome=outcome,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        truncated=truncated,
        duration_ms=DURATION_MS,
    )


def span_attributes(captured: InMemorySpanExporter, name: str) -> dict[str, Any]:
    (span,) = [s for s in captured.get_finished_spans() if s.name == name]
    return dict(span.attributes or {})


def recorded_search(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def _search(query: str, policy: Any) -> list[Candidate]:
        calls.append((query, policy))
        return [Candidate(title="t", url=URL, domain="reuters.com")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    return calls


def recorded_fetch(monkeypatch: pytest.MonkeyPatch) -> list[list[Candidate]]:
    calls: list[list[Candidate]] = []

    async def _fetch(candidates: list[Candidate], policy: Any) -> list[Source]:
        calls.append(candidates)
        return [Source(title="t", url=URL, text="text")]

    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)
    return calls


def fake_fetch(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    async def _call(*args: Any, **kwargs: Any) -> Any:
        return value

    monkeypatch.setattr(tools_module, "fetch_sources", _call)


@pytest.mark.anyio
async def test_a_search_returns_lines_and_spends_one_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls = recorded_search(monkeypatch)
    search_sources = tool_named(run, "search_sources")

    # Act
    result = await call(search_sources, {"query": "EU carbon border tax"})

    # Assert
    assert result.endswith("Searches left: 4.")
    assert run.searches == 1
    assert URL in run.candidates
    assert events_list == [
        ProgressFrame(node="deep_expert", label="Searching sources (1 of 5)...")
    ]
    assert calls == [("EU carbon border tax", EXPERT_SOURCES)]


@pytest.mark.anyio
async def test_a_blank_query_refuses_without_spending_a_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls = recorded_search(monkeypatch)
    search_sources = tool_named(run, "search_sources")

    # Act
    blank = await call(search_sources, {"query": "   "})
    empty = await call(search_sources, {"query": ""})

    # Assert
    assert blank == tools_module.EMPTY_QUERY_MESSAGE
    assert empty == tools_module.EMPTY_QUERY_MESSAGE
    assert calls == []
    assert run.searches == 0
    assert events_list == []


@pytest.mark.anyio
async def test_a_noisy_query_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    calls = recorded_search(monkeypatch)
    search_sources = tool_named(run, "search_sources")

    # Act
    await call(search_sources, {"query": "  EU   carbon tax  "})

    # Assert
    assert calls == [("EU carbon tax", EXPERT_SOURCES)]


@pytest.mark.anyio
async def test_the_search_cap_is_a_soft_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls = recorded_search(monkeypatch)
    search_sources = tool_named(run, "search_sources")

    # Act
    for _ in range(LIMITS.max_searches):
        await call(search_sources, {"query": "q"})
    sixteenth = await call(search_sources, {"query": "q"})

    # Assert
    assert sixteenth == tools_module.NO_SEARCHES_LEFT_MESSAGE
    assert calls == [("q", EXPERT_SOURCES)] * LIMITS.max_searches
    assert run.searches == LIMITS.max_searches
    assert events_list[-1].label == "Searching sources (5 of 5)..."


@pytest.mark.anyio
async def test_an_empty_search_returns_the_no_results_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: the search is spent, no candidates are stored, and the footer
    # still reports the remaining budget.
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls: list[str] = []

    async def _empty(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", _empty)
    search_sources = tool_named(run, "search_sources")

    # Act
    result = await call(search_sources, {"query": "nothing matches"})

    # Assert
    assert result == "No approved results for that query.\n\nSearches left: 4."
    assert calls == ["nothing matches"]
    assert run.searches == 1
    assert run.candidates == {}
    assert [event.label for event in events_list] == ["Searching sources (1 of 5)..."]


@pytest.mark.anyio
async def test_a_repeated_url_keeps_the_first_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: the second hit of the same URL carries a different title, but
    # the budget keeps the first seen (keep-first setdefault merge).
    run = ResearchRun(writer=(lambda e: None))
    calls: list[str] = []

    async def _two_hits(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        if len(calls) == 1:
            return [Candidate(title="first", url=URL, domain="reuters.com")]
        return [Candidate(title="second", url=URL, domain="reuters.com")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _two_hits)
    search_sources = tool_named(run, "search_sources")

    # Act
    await call(search_sources, {"query": "one"})
    await call(search_sources, {"query": "two"})

    # Assert
    assert run.candidates[URL].title == "first"


@pytest.mark.anyio
async def test_a_concurrent_read_fetches_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two same-URL reads started together share one in-flight fetch.

    The per-URL lock (`ResearchRun.lock_for`) serializes them: the loser finds
    the source cached. Without the lock both miss the cache before either
    stores, and the page is fetched twice (review thread, #129 c4142559750).
    """
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    recorded_search(monkeypatch)
    fetches = recorded_fetch(monkeypatch)
    search_sources = tool_named(run, "search_sources")
    read_source = tool_named(run, "read_source")
    await call(search_sources, {"query": "q"})

    # Act
    first, second = await asyncio.gather(
        call(read_source, {"url": URL}),
        call(read_source, {"url": URL}),
    )

    # Assert
    assert first.startswith("--- SOURCE ---")
    assert second.startswith("--- SOURCE ---")
    assert len(fetches) == 1


@pytest.mark.anyio
async def test_a_search_outage_is_a_hard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))

    async def _boom(query: str, policy: Any) -> list[Candidate]:
        raise SearchUnavailableError("brave down")

    monkeypatch.setattr(tools_module, "search_allowlisted", _boom)
    search_sources = tool_named(run, "search_sources")

    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await call(search_sources, {"query": "q"})
    assert run.searches == 1


@pytest.mark.anyio
async def test_read_source_refuses_an_unknown_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    fetches = recorded_fetch(monkeypatch)
    read_source = tool_named(run, "read_source")

    # Act
    result = await call(read_source, {"url": "https://unsearched.example/1"})

    # Assert
    assert result == tools_module.UNKNOWN_URL_MESSAGE
    assert fetches == []


@pytest.mark.anyio
async def test_read_source_returns_the_requested_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    recorded_search(monkeypatch)

    async def _redirect_fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url="https://other.example/redirected", text="text")]

    monkeypatch.setattr(tools_module, "fetch_sources", _redirect_fetch)
    search_sources = tool_named(run, "search_sources")
    read_source = tool_named(run, "read_source")
    await call(search_sources, {"query": "q"})

    # Act
    result = await call(read_source, {"url": URL})

    # Assert
    assert result.startswith("--- SOURCE ---")
    assert f"URL: {URL}" in result
    # Keyed by the URL the model asked for, even though the fetch redirected.
    assert URL in run.sources
    assert run.sources[URL].url == "https://other.example/redirected"
    assert events_list[-1].label == "Reading sources (1 so far)..."


@pytest.mark.anyio
async def test_a_second_read_does_not_fetch_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    recorded_search(monkeypatch)
    fetches = recorded_fetch(monkeypatch)
    search_sources = tool_named(run, "search_sources")
    read_source = tool_named(run, "read_source")
    await call(search_sources, {"query": "q"})

    # Act
    await call(read_source, {"url": URL})
    second = await call(read_source, {"url": URL})

    # Assert
    assert second.startswith("--- SOURCE ---")
    assert len(fetches) == 1


@pytest.mark.anyio
async def test_an_unreadable_page_returns_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    recorded_search(monkeypatch)
    fake_fetch(monkeypatch, [])
    search_sources = tool_named(run, "search_sources")
    read_source = tool_named(run, "read_source")
    await call(search_sources, {"query": "q"})

    # Act
    result = await call(read_source, {"url": URL})

    # Assert
    assert result == tools_module.UNREADABLE_MESSAGE
    assert URL not in run.sources


@pytest.mark.anyio
async def test_two_runs_do_not_share_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    recorded_search(monkeypatch)
    first = ResearchRun(writer=(lambda e: None))
    second = ResearchRun(writer=(lambda e: None))
    first_search = tool_named(first, "search_sources")
    tool_named(second, "search_sources")

    # Act
    await call(first_search, {"query": "q"})

    # Assert
    assert first.searches == 1
    assert second.searches == 0


@pytest.mark.anyio
async def test_a_computation_returns_output_and_spends_one_computation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model needs the printed numbers and how many runs it still has."""
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    run_python = tool_named(run, "run_python")
    sandbox = install_sandbox(monkeypatch, finished_run(stdout="6328.0\n"))

    # Act
    result = await call(run_python, {"code": CODE})

    # Assert
    assert result == "6328.0\n\nComputations left: 2."
    assert sandbox.codes == [CODE]
    assert run.computations == 1
    assert events_list == [
        ProgressFrame(node="deep_expert", label="Computing (1 of 3)...")
    ]


@pytest.mark.anyio
async def test_a_run_that_prints_nothing_asks_for_a_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A silent success would otherwise read as an empty result, not a missing `print`."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, finished_run(stdout="  \n"))

    # Act
    result = await call(run_python, {"code": "total = 1"})

    # Assert
    assert result == (
        "(The code printed nothing. `print` every result you need.)"
        "\n\nComputations left: 2."
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("spent", "expected_result", "expected_codes"),
    [
        (2, "42\n\nComputations left: 0.", [CODE]),
        (
            3,
            "No computations left. Do not call run_python again; "
            "write the answer from what you have.",
            [],
        ),
    ],
    ids=["one left", "none left"],
)
async def test_a_spent_computation_budget_answers_without_calling_the_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    spent: int,
    expected_result: str,
    expected_codes: list[str],
) -> None:
    """Each run costs a model turn; a spent budget is a message, never a failed turn."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run.computations = spent
    run_python = tool_named(run, "run_python")
    sandbox = install_sandbox(monkeypatch, finished_run(stdout="42\n"))

    # Act
    result = await call(run_python, {"code": CODE})

    # Assert
    assert result == expected_result
    assert sandbox.codes == expected_codes
    assert run.computations == 3


@pytest.mark.anyio
@pytest.mark.parametrize("code", ["", "  \n\t "], ids=["empty", "whitespace"])
async def test_blank_code_is_refused_without_spending_a_computation(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """Blank model output must not cost one of the turn's few runs."""
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    run_python = tool_named(run, "run_python")
    sandbox = install_sandbox(monkeypatch)

    # Act
    result = await call(run_python, {"code": code})

    # Assert
    assert result == "The code was empty. Send the Python to run."
    assert sandbox.codes == []
    assert run.computations == 0
    assert events_list == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failed", "message"),
    [
        (
            finished_run(
                "error", stderr="NameError: name 'x' is not defined\n", exit_code=1
            ),
            "The code failed (exit 1):\nNameError: name 'x' is not defined",
        ),
        (
            finished_run("timeout", exit_code=None),
            "The code ran past 10 seconds and was stopped. Simplify it.",
        ),
        (
            finished_run("oom", exit_code=1),
            "The code ran out of memory (256 MB). Use less data.",
        ),
        (
            finished_run(
                "refused",
                stderr="The sandbox is busy. Try again in a few seconds.",
                exit_code=None,
            ),
            "The sandbox is busy. Try again in a few seconds.",
        ),
    ],
    ids=["error", "timeout", "oom", "refused"],
)
async def test_each_failed_run_reads_as_a_message_the_model_can_act_on(
    monkeypatch: pytest.MonkeyPatch, failed: CodeRun, message: str
) -> None:
    """A bug in the model's code is its to fix; it must not end the turn."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, failed)

    # Act
    result = await call(run_python, {"code": CODE})

    # Assert
    assert result == f"{message}\n\nComputations left: 2."


@pytest.mark.anyio
async def test_a_truncated_run_tells_the_model_the_output_was_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the note the model would read a cut table as the whole result."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, finished_run(stdout="1\n2\n", truncated=True))

    # Act
    result = await call(run_python, {"code": CODE})

    # Assert
    assert result == "1\n2\n[Output cut at 10 KB.]\n\nComputations left: 2."


@pytest.mark.anyio
async def test_a_sandbox_outage_ends_the_turn_with_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deep turn never answers with numbers it meant to compute and could not."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, SandboxUnavailableError("sandbox down"))

    # Act + Assert
    with pytest.raises(SandboxUnavailableError):
        await call(run_python, {"code": CODE})
    assert run.computations == 1


@pytest.mark.anyio
async def test_the_run_python_span_records_each_decision(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A Phoenix trace alone must say what one computation did and cost."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run.computations = 1
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, finished_run(stdout="6328.0\n"))

    # Act
    await call(run_python, {"code": CODE})

    # Assert
    attributes = span_attributes(captured_spans, "run_python")
    assert attributes["turn.run_index"] == 2
    assert attributes["code.chars"] == 31
    assert attributes["code.lines"] == 2
    assert attributes["sandbox.outcome"] == "ok"
    assert attributes["sandbox.duration_ms"] == 120
    assert attributes["sandbox.exit_code"] == 0
    assert attributes["output.chars"] == 7
    assert attributes["output.truncated"] is False
    assert "error.type" not in attributes


@pytest.mark.anyio
async def test_the_run_python_span_names_a_failed_runs_outcome_as_its_error(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A stopped run has no exit code; the span says -1 and why it failed."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, finished_run("timeout", exit_code=None))

    # Act
    await call(run_python, {"code": CODE})

    # Assert
    attributes = span_attributes(captured_spans, "run_python")
    assert attributes["sandbox.outcome"] == "timeout"
    assert attributes["sandbox.exit_code"] == -1
    assert attributes["error.type"] == "timeout"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "spent", "outcome"),
    [("   ", 0, "empty"), (CODE, 3, "budget_spent")],
    ids=["blank code", "budget spent"],
)
async def test_the_run_python_span_records_why_nothing_ran(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    code: str,
    spent: int,
    outcome: str,
) -> None:
    """A call that never reached the sandbox must still explain itself in the trace."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run.computations = spent
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch)

    # Act
    await call(run_python, {"code": code})

    # Assert
    attributes = span_attributes(captured_spans, "run_python")
    assert attributes["sandbox.outcome"] == outcome


@pytest.mark.anyio
async def test_the_run_python_span_records_an_unreachable_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """The trace of a failed turn must point at the sandbox, not at the model."""
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    run_python = tool_named(run, "run_python")
    install_sandbox(monkeypatch, SandboxUnavailableError("sandbox down"))

    # Act + Assert
    with pytest.raises(SandboxUnavailableError):
        await call(run_python, {"code": CODE})
    attributes = span_attributes(captured_spans, "run_python")
    assert attributes["sandbox.outcome"] == "unreachable"
    assert attributes["error.type"] == "SandboxUnavailableError"
