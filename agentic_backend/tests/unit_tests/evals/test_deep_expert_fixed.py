"""Unit tests for `evals.deep_expert_fixed`."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from evals.deep_expert_fixed import run_deep_expert_fixed
from frames import NoticeEvent, ProgressFrame

PROGRESS_LABEL = "Searching sources (1 of 5)..."


async def _research_with_one_step(query: str, writer: Any) -> str:
    """Stands in for `research`: writes one progress frame and one notice, returns a draft."""
    writer(ProgressFrame(node="deep_expert", label=PROGRESS_LABEL))
    writer(NoticeEvent(text="Not a step label."))
    return "The deep answer."


class _ExpertGraph:
    """Stands in for the expert's compiled graph, which the eval runs live as the baseline."""

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, str]:
        return {"answer": "The expert answer."}


@pytest.mark.anyio
async def test_a_progress_frame_reaches_the_eval_progress_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The eval records each step label a deep run writes, so a dropped frame would leave `progress` empty and no check would fail."""
    # Arrange
    deep_package = importlib.import_module("agents.deep_expert")
    expert_package = importlib.import_module("agents.expert")
    monkeypatch.setattr(deep_package, "research", _research_with_one_step)
    monkeypatch.setattr(expert_package, "graph", _ExpertGraph())

    # Act
    output = await run_deep_expert_fixed({"query": "Who objected to 5%?"})

    # Assert
    assert output["progress"] == [PROGRESS_LABEL]
