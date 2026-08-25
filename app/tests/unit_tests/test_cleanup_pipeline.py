from __future__ import annotations

import httpx

import api
import search
from graph import invoke_pipeline
from llm import LLMInvocationError
from models import Source, build_initial_pipeline_state
from nodes.generic_analyst import generic_analyst_agent


class _FakeGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    def invoke(self, state: dict, config: dict) -> dict:
        self.calls.append((state, config))
        return {"final_output": "rendered"}


def test_invoke_pipeline_builds_independent_runtime_state() -> None:
    graph = _FakeGraph()

    assert invoke_pipeline(graph, "English query", "english") == "rendered"
    assert invoke_pipeline(graph, "Polskie pytanie", "polish") == "rendered"

    english_state, english_config = graph.calls[0]
    polish_state, polish_config = graph.calls[1]
    assert english_state["language"] == "english"
    assert polish_state["language"] == "polish"
    assert english_config["configurable"]["infosphere_sources"] != polish_config[
        "configurable"
    ]["infosphere_sources"]
    assert english_state is not polish_state


def test_chunk_text_ignores_non_text_content_blocks() -> None:
    assert api._chunk_text("text") == "text"
    assert api._chunk_text(
        [{"type": "text", "text": "one"}, {"type": "tool_call", "name": "search"}]
    ) == "one"
    assert api._chunk_text([{"type": "reasoning", "text": "hidden"}]) == ""
    assert api._chunk_text([]) == ""


def test_search_transient_classifier_only_retries_safe_failures() -> None:
    request = httpx.Request("GET", "https://example.test")
    retryable = httpx.HTTPStatusError(
        "rate limited", request=request, response=httpx.Response(429, request=request)
    )
    not_retryable = httpx.HTTPStatusError(
        "bad request", request=request, response=httpx.Response(400, request=request)
    )

    assert search._is_transient_search_error(httpx.TimeoutException("timeout"))
    assert search._is_transient_search_error(retryable)
    assert not search._is_transient_search_error(not_retryable)


def test_analyst_llm_failure_returns_source_note_fallback() -> None:
    state = build_initial_pipeline_state("Question", language="english")
    state["left_sources"] = [
        Source(
            id="L1",
            title="Source",
            url="https://example.test",
            notes="A source-backed finding.",
        )
    ]

    def _raise_llm_error(**_kwargs):
        raise LLMInvocationError("provider unavailable")

    result = generic_analyst_agent(
        state,
        {"left": [("Source", "https://example.test")]},
        "english",
        lane_key="left",
        ideology="leftist",
        model_key="left_analyst",
        log_label="Left",
        perspective_label="Left",
        fallback_limit=2,
        invoke_chain=_raise_llm_error,
    )

    assert result["left_claims"][0].source_ids == ["L1"]
    assert result["errors"] == [
        {
            "node": "left_analyst",
            "error_type": "LLMInvocationError",
            "message": "provider unavailable",
        }
    ]
