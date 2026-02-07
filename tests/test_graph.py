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


def _make_fake_llm_json(infosphere: str):
    is_polish = infosphere == "polish"

    def _fake_llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
        if "Task: Provide 3-5 analytically cautious claims" in user:
            if "perspective: leftist" in user:
                return {
                    "claims": [
                        {
                            "text": "Polish left claim about policy impacts."
                            if is_polish
                            else "Left claim about policy impacts.",
                            "source_ids": ["S1"],
                        }
                    ]
                }
            if "perspective: centrist" in user:
                return {
                    "claims": [
                        {
                            "text": "Polish centrist claim balancing competing goals."
                            if is_polish
                            else "Centrist claim balancing competing goals.",
                            "source_ids": ["S2"],
                        }
                    ]
                }
            if "perspective: people" in user:
                return {
                    "claims": [
                        {
                            "text": "Polish people claim reflecting public sentiment."
                            if is_polish
                            else "People claim reflecting public sentiment.",
                            "source_ids": ["S1"],
                        }
                    ]
                }
            return {
                "claims": [
                    {
                        "text": "Polish right claim focused on market incentives."
                        if is_polish
                        else "Right claim focused on market incentives.",
                        "source_ids": ["S1", "S2"],
                    }
                ]
            }

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
            return {"results": results}

        if "Task: Provide a neutral synthesis" in user:
            return {
                "synthesis": "Overall evidence suggests mixed outcomes with partial support."
                if not is_polish
                else "Polish evidence suggests mixed outcomes with partial support.",
            }

        return {}

    return _fake_llm_json


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
        "people": _seed_sources("people"),
        "fact": _seed_sources("fact"),
    }

    # execute
    fake_llm_json = _make_fake_llm_json(infosphere)
    with patch("geopoliticai.claims.llm_json", fake_llm_json), patch(
        "geopoliticai.fact_check.llm_json", fake_llm_json
    ), patch("geopoliticai.summarizer.llm_json", fake_llm_json):
        output = run_pipeline(
            "Test query", seed_sources=seed_sources, infosphere=infosphere
        )

    # assert
    assert "Factual Background" in output or "Tło faktograficzne" in output
    assert expected_left_claim in output
    assert expected_reference in output
    assert "Reddit" in output
    if infosphere == "polish":
        assert "Perspektywa lewicowa" in output
        assert "Perspektywa centrowa" in output
        assert "Perspektywa prawicowa" in output
        assert "Perspektywa społeczna" in output
        assert "Wyniki weryfikacji faktów" in output
        assert "Synteza i najlepiej potwierdzone wnioski" in output
        assert "Polish centrist claim balancing competing goals." in output
        assert "Polish people claim reflecting public sentiment." in output
        assert "Polish right claim focused on market incentives." in output
        assert "Evidence supports parts but not all details (PL)." in output
        assert "Polish evidence suggests mixed outcomes with partial support." in output
    else:
        assert "Left Perspective" in output
        assert "Centrist Perspective" in output
        assert "Right Perspective" in output
        assert "People's Perspective" in output
        assert "Fact Check Results" in output
        assert "Synthesis & Best-Supported Conclusion" in output
        assert "Centrist claim balancing competing goals." in output
        assert "People claim reflecting public sentiment." in output
        assert "Right claim focused on market incentives." in output
        assert "Evidence supports parts but not all details." in output
        assert "Overall evidence suggests mixed outcomes with partial support." in output
    assert "PARTIALLY TRUE" in output
