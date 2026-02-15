from __future__ import annotations

from typing import Callable, List

from geopoliticai.models import PipelineState
from geopoliticai.render import (
    merge_sources,
    render_claims,
    render_fact_checks,
    render_reference_list,
    render_sources,
)


def make_supervisor_step(
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> Callable[[PipelineState], PipelineState]:
    if language == "polish":
        labels = {
            "factual": "1. 🔎 Tło faktograficzne (z wyszukiwania)",
            "left": "2. 🔴 Perspektywa lewicowa",
            "centrist": "3. 🟡 Perspektywa centrowa",
            "right": "4. 🔵 Perspektywa prawicowa",
            "fact": "5. ✅ Wyniki weryfikacji faktów",
            "synthesis": "6. ⚖️ Synteza i najlepiej potwierdzone wnioski",
            "decision": "7. 🧭 Decyzja arbitra",
            "refs": "Preferowane źródła:",
        }
    else:
        labels = {
            "factual": "1. 🔎 Factual Background (from Web Searcher)",
            "left": "2. 🔴 Left Perspective",
            "centrist": "3. 🟡 Centrist Perspective",
            "right": "4. 🔵 Right Perspective",
            "fact": "5. ✅ Fact Check Results",
            "synthesis": "6. ⚖️ Synthesis & Best-Supported Conclusion",
            "decision": "7. 🧭 Arbiter Decision",
            "refs": "Preferred references:",
        }

    def supervisor(state: PipelineState) -> PipelineState:
        output: List[str] = []
        output.append(labels["factual"])
        output.append(render_sources(merge_sources(state)))
        output.append("")
        output.append(labels["left"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["left"]))
        output.append(render_claims(state["left_claims"]))
        output.append("")
        output.append(labels["centrist"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["centrist"]))
        output.append(render_claims(state["centrist_claims"]))
        output.append("")
        output.append(labels["right"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["right"]))
        output.append(render_claims(state["right_claims"]))
        output.append("")
        output.append(labels["fact"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["fact"]))
        output.append(render_fact_checks(state["fact_checks"]))
        output.append("")
        output.append(labels["synthesis"])
        output.append(state["synthesis"])
        output.append("")
        output.append(labels["decision"])
        output.append(f"- {state['decision']}: {state['decision_rationale']}")
        return {**state, "final_output": "\n".join(output)}

    return supervisor
