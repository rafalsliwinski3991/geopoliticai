from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

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


def _make_fake_invoke_structured_chain(infosphere: str):
    is_polish = infosphere == "polish"

    def _fake_invoke_structured_chain(*, schema, system_prompt: str, human_prompt: str, variables: dict, temperature: float = 0.2):

        class _Obj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        user = human_prompt.format(**variables)
        if "Task: Provide 3-5 analytically cautious claims" in user:
            if "perspective: leftist" in user:
                return _Obj(claims=[_Obj(text=("Polish left claim about policy impacts." if is_polish else "Left claim about policy impacts."), source_ids=["S1"])])
            if "perspective: centrist" in user:
                return _Obj(claims=[_Obj(text=("Polish centrist claim balancing competing goals." if is_polish else "Centrist claim balancing competing goals."), source_ids=["S2"])])
            return _Obj(claims=[_Obj(text=("Polish right claim focused on market incentives." if is_polish else "Right claim focused on market incentives."), source_ids=["S1", "S2"])])

        if "Task: Fact-check each claim" in user:
            lines = []
            capture = False
            for line in user.splitlines():
                if line.strip() == "Claims:":
                    capture = True
                    continue
                if capture and line.strip().startswith(
                    "Preferred fact-check references"
                ):
                    break
                if capture and line.strip().startswith("- "):
                    lines.append(line.strip()[2:])
            results = []
            for line in lines:
                claim_text = line.split(" (Sources:", 1)[0].strip()
                if claim_text:
                    results.append(
                        {
                            "claim_text": claim_text,
                            "verdict": "PARTIALLY TRUE",
                            "rationale": "Evidence supports parts but not all details."
                            if not is_polish
                            else "Evidence supports parts but not all details (PL).",
                            "source_ids": ["S1"],
                        }
                    )
            return _Obj(results=[_Obj(**r) for r in results])

        if "Task: Provide a neutral synthesis" in user:
            return _Obj(synthesis=("Overall evidence suggests mixed outcomes with partial support." if not is_polish else "Polish evidence suggests mixed outcomes with partial support."))

        return _Obj()

    return _fake_invoke_structured_chain


@pytest.mark.parametrize(
    "infosphere,expected_left_claim,expected_reference",
    [
        ("english", "Left claim about policy impacts.", "Jacobin"),
        ("polish", "Polish left claim about policy impacts.", "Krytyka Polityczna"),
    ],
)
def test_run_pipeline(infosphere, expected_left_claim, expected_reference):
    # prepare
    seed_sources = {
        "left": _seed_sources("left"),
        "centrist": _seed_sources("centrist"),
        "right": _seed_sources("right"),
        "fact": _seed_sources("fact"),
    }

    # execute
    fake_invoke = _make_fake_invoke_structured_chain(infosphere)
    with patch("geopoliticai.agents.left_analyst.invoke_structured_chain", fake_invoke), patch(
        "geopoliticai.agents.center_analyst.invoke_structured_chain", fake_invoke
    ), patch("geopoliticai.agents.right_analyst.invoke_structured_chain", fake_invoke), patch(
        "geopoliticai.agents.cross_check_facts.invoke_structured_chain", fake_invoke
    ), patch("geopoliticai.agents.compose_final.invoke_structured_chain", fake_invoke):
        output = run_pipeline(
            "Test query", seed_sources=seed_sources, infosphere=infosphere
        )

    # assert
    assert "Factual Background" in output or "Tło faktograficzne" in output
    assert expected_left_claim in output
    assert expected_reference in output
    if infosphere == "polish":
        assert "Perspektywa lewicowa" in output
        assert "Perspektywa centrowa" in output
        assert "Perspektywa prawicowa" in output
        assert "Wyniki weryfikacji faktów" in output
        assert "Synteza i najlepiej potwierdzone wnioski" in output
        assert "Polish centrist claim balancing competing goals." in output
        assert "Polish right claim focused on market incentives." in output
        assert "Evidence supports parts but not all details (PL)." in output
        assert "Polish evidence suggests mixed outcomes with partial support." in output
    else:
        assert "Left Perspective" in output
        assert "Centrist Perspective" in output
        assert "Right Perspective" in output
        assert "Fact Check Results" in output
        assert "Synthesis & Best-Supported Conclusion" in output
        assert "Centrist claim balancing competing goals." in output
        assert "Right claim focused on market incentives." in output
        assert "Evidence supports parts but not all details." in output
        assert "Overall evidence suggests mixed outcomes with partial support." in output
    assert "PARTIALLY TRUE" in output
    assert "Arbiter Decision" in output or "Decyzja arbitra" in output
    assert "EXECUTE" in output
