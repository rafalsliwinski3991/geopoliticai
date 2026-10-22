"""Unit tests for `evals.expert_live`; no Brave search or model call happens."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from evals.expert_live import run_expert_live
from models import Source


class ScriptedExpertGraph:
    """A stand-in for the expert's graph: returns one scripted result, raises when called again."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.results = [result]

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.results.pop(0)


@pytest.mark.anyio
async def test_the_live_expert_returns_its_answer_and_the_pages_it_read() -> None:
    """The judges check links and faithfulness against the pages the run read, so the output must carry them."""
    # Arrange
    page = Source(title="T", url="https://news.example/a", text="body", author="Ann")
    graph = ScriptedExpertGraph({"answer": "An answer.", "sources": [page]})

    # Act
    with patch("agents.expert.graph", graph):
        output = await run_expert_live({"query": "q"})

    # Assert
    assert output == {
        "answer": "An answer.",
        "sources": [
            {
                "title": "T",
                "url": "https://news.example/a",
                "text": "body",
                "author": "Ann",
            }
        ],
    }
