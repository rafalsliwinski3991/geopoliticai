from __future__ import annotations

from unittest.mock import patch

from geopoliticai.agents.compose_final import compose_final_agent
from geopoliticai.models import Claim, FactCheckResult


def _state() -> dict:
    left_claim = Claim(text="Left claim text", source_ids=["L1"])
    right_claim = Claim(text="Right claim text", source_ids=["R1"])
    return {
        "query": "Who started conflict between A and B?",
        "left_claims": [left_claim],
        "centrist_claims": [],
        "right_claims": [right_claim],
        "people_claims": [],
        "left_sources": [],
        "centrist_sources": [],
        "right_sources": [],
        "people_sources": [],
        "fact_sources": [],
        "fact_checks": [
            FactCheckResult(
                claim=left_claim,
                verdict="TRUE",
                rationale="Supported by provided sources.",
            )
        ],
        "synthesis": "",
    }


def test_compose_final_fallback_lists_claims_with_authors_and_verdicts() -> None:
    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    with patch(
        "geopoliticai.agents.compose_final.invoke_structured_chain",
        return_value=_Obj(synthesis="Short answer: Something."),
    ):
        result = compose_final_agent(_state(), language="english")

    synthesis = result["synthesis"]
    assert "Claims by perspective:" in synthesis
    assert "[Left] Left claim text" in synthesis
    assert "Verdict: TRUE" in synthesis
    assert "[Right] Right claim text" in synthesis
    assert "Verdict: NOT CHECKED" in synthesis


def test_compose_final_prompt_includes_all_fact_verdicts() -> None:
    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    state = _state()
    right_claim = state["right_claims"][0]
    state["fact_checks"].append(
        FactCheckResult(
            claim=right_claim,
            verdict="MISLEADING",
            rationale="Insufficient evidence in provided sources.",
        )
    )
    captured_users: list[str] = []

    def _fake_invoke(*, human_prompt: str, variables: dict, **_kwargs):
        captured_users.append(human_prompt.format(**variables))
        return _Obj(
            synthesis="Short answer: Direct answer.\nDetail line with concrete support."
        )

    with patch("geopoliticai.agents.compose_final.invoke_structured_chain", _fake_invoke):
        compose_final_agent(state, language="english")

    assert captured_users
    prompt = captured_users[0]
    assert "All fact-check results (all verdicts):" in prompt
    assert "- MISLEADING: Right claim text" in prompt
