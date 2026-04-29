from models import Claim, FactCheckResult, build_initial_pipeline_state
from nodes import compose_final

_ENGLISH_CONFIG = {"configurable": {"language": "english"}}


def _state_with_mixed_verdicts() -> dict:
    state = build_initial_pipeline_state(
        "Who started the conflict?",
        language="english",
    )
    state["left_claims"] = [
        Claim(text="Claim TRUE from left.", source_ids=["L1"]),
        Claim(text="Claim FALSE from left.", source_ids=["L2"]),
    ]
    state["centrist_claims"] = [
        Claim(text="Claim TRUE from left.", source_ids=["C1"]),
    ]
    state["fact_checks"] = [
        FactCheckResult(
            claim=Claim(text="Claim TRUE from left.", source_ids=["L1"]),
            verdict="TRUE",
            rationale="Supported.",
        ),
        FactCheckResult(
            claim=Claim(text="Claim FALSE from left.", source_ids=["L2"]),
            verdict="FALSE",
            rationale="Contradicted.",
        ),
        FactCheckResult(
            claim=Claim(
                text="TRUE claim only in fact-check output.", source_ids=["F1"]
            ),
            verdict="TRUE",
            rationale="Supported in verification.",
        ),
    ]
    return state


def test_usable_fact_checks_filters_and_sorts_by_confidence() -> None:
    state = _state_with_mixed_verdicts()
    state["fact_checks"][0].confidence = 0.82
    state["fact_checks"][1].verdict = "UNVERIFIED"
    state["fact_checks"][1].confidence = 0.20
    state["fact_checks"][2].confidence = 0.95

    usable = compose_final._usable_fact_checks(state)  # type: ignore[arg-type]

    assert [item.claim.text for item in usable] == [
        "TRUE claim only in fact-check output.",
        "Claim TRUE from left.",
    ]
    assert [item.confidence for item in usable] == [0.95, 0.82]


def test_compose_final_returns_fallback_when_no_usable_claims() -> None:
    state = build_initial_pipeline_state("Any question", language="english")
    state["left_claims"] = [Claim(text="Unverified claim.", source_ids=["L1"])]
    state["fact_checks"] = [
        FactCheckResult(
            claim=Claim(text="Unverified claim.", source_ids=["L1"]),
            verdict="UNVERIFIED",
            confidence=0.20,
            rationale="Insufficient evidence.",
        )
    ]

    result = compose_final.compose_final_agent(state, _ENGLISH_CONFIG)  # type: ignore[arg-type]

    assert result["synthesis"].startswith(
        "Short answer: No answer can be supported by sufficiently verified claims."
    )


def test_compose_final_prompt_uses_weighted_claims(monkeypatch) -> None:
    state = _state_with_mixed_verdicts()
    captured: dict[str, str] = {}

    def _fake_invoke_structured_chain(**kwargs):
        if kwargs["schema"] is compose_final.SynthesisOutput:
            captured.update(kwargs["variables"])
        else:
            assert kwargs["schema"] is compose_final.AlignmentOutput
        return kwargs["schema"](
            synthesis="Short answer: Answered from weighted claims."
        )

    monkeypatch.setattr(
        compose_final, "invoke_structured_chain", _fake_invoke_structured_chain
    )

    result = compose_final.compose_final_agent(state, _ENGLISH_CONFIG)  # type: ignore[arg-type]

    assert "Claim TRUE from left." in captured["weighted_claims_block"]
    assert "TRUE claim only in fact-check output." in captured["weighted_claims_block"]
    assert "Claim FALSE from left." not in captured["weighted_claims_block"]
    assert result["synthesis"] == "Short answer: Answered from weighted claims."


def test_compose_final_fallback_when_llm_raises(monkeypatch) -> None:
    state = _state_with_mixed_verdicts()

    def _raise_invoke(**_kwargs):
        raise ValueError("OpenAI returned an empty JSON response body.")

    monkeypatch.setattr(compose_final, "invoke_structured_chain", _raise_invoke)

    result = compose_final.compose_final_agent(state, _ENGLISH_CONFIG)  # type: ignore[arg-type]

    assert result["synthesis"].startswith(
        "Short answer: Based on weighted verified claims, Claim TRUE from left."
    )
    assert "Weighted claims:" in result["synthesis"]
