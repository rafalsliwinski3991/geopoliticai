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


def _fake_llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
    if "Task: Provide 3-5 analytically cautious claims" in user:
        if "perspective: leftist" in user:
            return {
                "claims": [
                    {
                        "text": "Left claim about policy impacts.",
                        "source_ids": ["S1"],
                    }
                ]
            }
        if "perspective: centrist" in user:
            return {
                "claims": [
                    {
                        "text": "Centrist claim balancing competing goals.",
                        "source_ids": ["S2"],
                    }
                ]
            }
        return {
            "claims": [
                {
                    "text": "Right claim focused on market incentives.",
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
            if capture and line.strip().startswith("Preferred fact-check references"):
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
                        "rationale": "Evidence supports parts but not all details.",
                        "source_ids": ["S1"],
                    }
                )
        return {"results": results}

    if "Task: Provide a neutral synthesis" in user:
        return {
            "synthesis": "Overall evidence suggests mixed outcomes with partial support."
        }

    return {}


def test_run_pipeline():
    # prepare
    seed_sources = {
        "left": _seed_sources("left"),
        "centrist": _seed_sources("centrist"),
        "right": _seed_sources("right"),
        "fact": _seed_sources("fact"),
    }

    # execute
    with patch("geopoliticai.claims.llm_json", _fake_llm_json), patch(
        "geopoliticai.fact_check.llm_json", _fake_llm_json
    ), patch("geopoliticai.summarizer.llm_json", _fake_llm_json):
        output = run_pipeline("Test query", seed_sources=seed_sources)

    # assert
    assert "Factual Background" in output
    assert "Left Perspective" in output
    assert "Centrist Perspective" in output
    assert "Right Perspective" in output
    assert "Fact Check Results" in output
    assert "Synthesis" in output
    assert "Left claim about policy impacts." in output
    assert "Centrist claim balancing competing goals." in output
    assert "Right claim focused on market incentives." in output
    assert "PARTIALLY TRUE" in output
    assert "Overall evidence suggests mixed outcomes with partial support." in output
