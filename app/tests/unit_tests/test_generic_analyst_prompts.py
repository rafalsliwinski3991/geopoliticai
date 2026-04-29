from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel

from models import ResearchPlan, Source
from nodes.generic_analyst import generic_analyst_agent


@dataclass
class PlanWithDomain:
    domain: str


def _infosphere_sources() -> dict[str, list[tuple[str, str]]]:
    return {
        "left": [("Jacobin", "https://jacobin.com")],
        "centrist": [("Brookings", "https://www.brookings.edu")],
        "right": [("Heritage", "https://www.heritage.org")],
        "people": [("Reddit", "https://www.reddit.com")],
    }


def _state_for_lane(lane_key: str, research_plan: Any) -> dict[str, Any]:
    source_id = {
        "left": "L1",
        "centrist": "C1",
        "right": "R1",
        "people": "P1",
    }[lane_key]
    return {
        "query": "What are the effects of the policy?",
        "research_plan": research_plan,
        f"{lane_key}_sources": [
            Source(
                id=source_id,
                title="Policy report",
                url="https://example.com/report",
                notes="The report describes policy costs and public response.",
            )
        ],
    }


def _capture_first_prompt(lane_key: str, research_plan: Any) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []

    def fake_invoke_chain(**kwargs: Any) -> BaseModel:
        calls.append(kwargs)
        source_id = kwargs["variables"]["example_source_id"]
        return kwargs["schema"](
            claims=[
                {
                    "text": f"According to {source_id}, the policy has measurable effects.",
                    "source_ids": [source_id],
                }
            ]
        )

    generic_analyst_agent(
        _state_for_lane(lane_key, research_plan),  # type: ignore[arg-type]
        _infosphere_sources(),
        "english",
        lane_key=lane_key,
        ideology=f"{lane_key} ideology",
        model_key=f"{lane_key}_analyst",
        log_label=lane_key.title(),
        perspective_label=lane_key.title(),
        fallback_limit=2,
        invoke_chain=fake_invoke_chain,
    )

    assert calls
    return calls[0]


@pytest.mark.parametrize(
    ("lane_key", "expected_lens"),
    [
        ("left", "power, inequality"),
        ("centrist", "pragmatic trade-offs"),
        ("right", "individual agency"),
        ("people", "lived experience"),
    ],
)
def test_analyst_prompt_uses_lane_specific_lens(
    lane_key: str,
    expected_lens: str,
) -> None:
    call = _capture_first_prompt(lane_key, PlanWithDomain(domain="geopolitics"))

    assert expected_lens in call["system_prompt"]
    assert expected_lens in call["variables"]["lane_lens"]
    assert "from the perspective: {" not in call["human_prompt"]


@pytest.mark.parametrize(
    ("research_plan", "expected_guidance"),
    [
        (PlanWithDomain(domain="economics"), "GDP impact"),
        ({"domain": "social policy"}, "household impact"),
    ],
)
def test_analyst_prompt_includes_domain_guidance(
    research_plan: Any,
    expected_guidance: str,
) -> None:
    call = _capture_first_prompt("centrist", research_plan)

    assert expected_guidance in call["variables"]["domain_guidance"]


def test_analyst_prompt_handles_old_research_plan_without_domain() -> None:
    call = _capture_first_prompt("left", ResearchPlan(queries=["policy effects"]))

    assert "No specific research domain was provided" in call["variables"]["domain_guidance"]


def test_analyst_prompt_requires_reasoning_and_contradictory_evidence() -> None:
    call = _capture_first_prompt("right", PlanWithDomain(domain="military"))

    reasoning_instruction = call["variables"]["reasoning_instruction"]
    assert "why this perspective reaches the conclusion" in reasoning_instruction
    assert "contradicts this perspective" in reasoning_instruction
    assert "{reasoning_instruction}" in call["human_prompt"]
