from typing import Any

import planning


def test_build_research_plan_uses_structured_llm(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_invoke_structured_chain(**kwargs):
        captured.update(kwargs)
        return planning.ResearchPlanOutput(
            entities=["China", "Iowa", "CFIUS", "China"],
            domain="economics",
            queries=[
                "China farmland Iowa ownership data",
                "CFIUS agricultural land review process",
                "Iowa state legislation foreign farmland purchases",
                "China farmland Iowa ownership data",
            ],
            must_find=["ownership totals", "review authority"],
        )

    monkeypatch.setattr(
        planning, "invoke_structured_chain", fake_invoke_structured_chain
    )

    result = planning.build_research_plan(
        {"query": "China buying farmland in Iowa", "language": "english"}  # type: ignore[arg-type]
    )

    plan = result["research_plan"]
    assert captured["schema"] is planning.ResearchPlanOutput
    assert captured["variables"] == {
        "query": "China buying farmland in Iowa",
        "response_language": "English",
    }
    assert plan.entities == ["China", "Iowa", "CFIUS"]
    assert plan.queries == [
        "China farmland Iowa ownership data",
        "CFIUS agricultural land review process",
        "Iowa state legislation foreign farmland purchases",
    ]
    assert plan.must_find == ["ownership totals", "review authority"]
    assert plan.domain == "economics"


def test_build_research_plan_falls_back_when_llm_fails(monkeypatch) -> None:
    def failing_invoke_structured_chain(**_kwargs):
        raise RuntimeError("OpenAI unavailable")

    monkeypatch.setattr(planning, "invoke_structured_chain", failing_invoke_structured_chain)

    result = planning.build_research_plan(
        {"query": "NATO missile defense budget", "language": "english"}  # type: ignore[arg-type]
    )

    plan = result["research_plan"]
    assert plan.queries[0] == "NATO missile defense budget"
    assert len(plan.queries) >= 3
    assert plan.must_find == [
        "most relevant recent development",
        "primary-source or official confirmation",
        "clearest policy or public-impact consequence",
    ]
    assert plan.entities == ["NATO"]
    assert plan.domain == "military"
