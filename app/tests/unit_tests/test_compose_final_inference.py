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


def test_true_claims_filters_only_true_verdicts() -> None:
    state = _state_with_mixed_verdicts()

    true_claims = compose_final._true_claims(state)  # type: ignore[arg-type]

    assert [claim.text for claim in true_claims] == [
        "Claim TRUE from left.",
        "TRUE claim only in fact-check output.",
    ]


def test_compose_final_returns_fallback_when_no_true_claims() -> None:
    state = build_initial_pipeline_state("Any question", language="english")
    state["left_claims"] = [Claim(text="Unverified claim.", source_ids=["L1"])]
    state["fact_checks"] = [
        FactCheckResult(
            claim=Claim(text="Unverified claim.", source_ids=["L1"]),
            verdict="MISLEADING",
            rationale="Insufficient evidence.",
        )
    ]

    result = compose_final.compose_final_agent(state, _ENGLISH_CONFIG)  # type: ignore[arg-type]

    assert result["synthesis"].startswith(
        "Short answer: No answer can be supported by verified TRUE claims."
    )


def test_compose_final_prompt_uses_true_claims_only(monkeypatch) -> None:
    state = _state_with_mixed_verdicts()
    captured: dict[str, str] = {}

    def _fake_invoke_structured_chain(**kwargs):
        captured.update(kwargs["variables"])
        return compose_final.SynthesisOutput(
            synthesis="Short answer: Answered from TRUE claims."
        )

    monkeypatch.setattr(
        compose_final, "invoke_structured_chain", _fake_invoke_structured_chain
    )

    result = compose_final.compose_final_agent(state, _ENGLISH_CONFIG)  # type: ignore[arg-type]

    assert "Claim TRUE from left." in captured["true_claims_block"]
    assert "TRUE claim only in fact-check output." in captured["true_claims_block"]
    assert "Claim FALSE from left." not in captured["true_claims_block"]
    assert result["synthesis"] == "Short answer: Answered from TRUE claims."


def test_compose_final_fallback_when_llm_raises(monkeypatch) -> None:
    state = _state_with_mixed_verdicts()

    def _raise_invoke(**_kwargs):
        raise ValueError("OpenAI returned an empty JSON response body.")

    monkeypatch.setattr(compose_final, "invoke_structured_chain", _raise_invoke)

    result = compose_final.compose_final_agent(state, _ENGLISH_CONFIG)  # type: ignore[arg-type]

    assert result["synthesis"].startswith(
        "Short answer: Based on verified TRUE claims, Claim TRUE from left."
    )
    assert "Verified TRUE claims:" in result["synthesis"]
