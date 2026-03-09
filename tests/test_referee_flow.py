from __future__ import annotations

from typing import List
from unittest.mock import patch

from geopoliticai.graph import run_pipeline
from geopoliticai.models import Source


def _seed_sources(label: str) -> List[Source]:
    return [
        Source(
            id="S1",
            title=f"{label} Source One",
            url=f"https://example.com/{label}/1",
            notes=f"{label} notes one.",
        ),
        Source(
            id="S2",
            title=f"{label} Source Two",
            url=f"https://example.com/{label}/2",
            notes=f"{label} notes two.",
        ),
    ]


def _fake_invoke_for_blocking(*, human_prompt: str, variables: dict, **_kwargs):
    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    user = human_prompt.format(**variables)
    if "Task: Provide 3-5 analytically cautious claims" in user:
        # Empty source_ids make claims unsupported and force referee blocking.
        return _Obj(claims=[_Obj(text="A claim without citations.", source_ids=[])])

    if "Task: Fact-check each claim" in user:
        raise AssertionError("Fact-check should not run when referee blocks.")

    if (
        "Task: Provide a user-friendly synthesis" in user
        or "Task: Provide a synthesis that answers the user query directly and clearly."
        in user
    ):
        raise AssertionError("Compose final should not run when referee blocks.")

    return _Obj()


def test_pipeline_stops_after_referee_block() -> None:
    seed_sources = {
        "left": _seed_sources("left"),
        "centrist": _seed_sources("centrist"),
        "right": _seed_sources("right"),
        "people": _seed_sources("people"),
        "fact": _seed_sources("fact"),
    }

    with patch(
        "geopoliticai.agents.left_analyst.invoke_structured_chain",
        _fake_invoke_for_blocking,
    ), patch(
        "geopoliticai.agents.center_analyst.invoke_structured_chain",
        _fake_invoke_for_blocking,
    ), patch(
        "geopoliticai.agents.right_analyst.invoke_structured_chain",
        _fake_invoke_for_blocking,
    ), patch(
        "geopoliticai.agents.people_analyst.invoke_structured_chain",
        _fake_invoke_for_blocking,
    ), patch(
        "geopoliticai.agents.cross_check_facts.invoke_structured_chain",
        _fake_invoke_for_blocking,
    ), patch(
        "geopoliticai.agents.compose_final.invoke_structured_chain",
        _fake_invoke_for_blocking,
    ):
        output = run_pipeline(
            "Test query",
            seed_sources=seed_sources,
            infosphere="english",
            report_mode="full",
        )

    assert "A reliable answer cannot be provided with the current verification state." in output
    assert "Unsupported claims: 4" in output
    assert "Fact-check: 0 verdicts" in output
