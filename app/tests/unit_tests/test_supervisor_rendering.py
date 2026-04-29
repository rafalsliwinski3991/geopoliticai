from models import Claim, Source, build_initial_pipeline_state
from nodes.supervisor import supervisor_step


def test_supervisor_replaces_source_ids_with_human_labels() -> None:
    state = build_initial_pipeline_state(
        "Czy Ukraina wygra z Rosją?",
        language="polish",
    )
    state["synthesis"] = "Krotka odpowiedz: To zależy od wsparcia."
    state["left_sources"] = [
        Source(
            id="L3",
            title="Siły Zbrojne Ukrainy przechodzą do defensywy",
            url="https://example.com/left",
            notes="Opis sytuacji na froncie.",
        )
    ]
    state["left_claims"] = [
        Claim(
            text="Według L3, Ukraina może utrzymać obronę przy wsparciu.",
            source_ids=["L3"],
        )
    ]

    result = supervisor_step(
        state,
        {"configurable": {"language": "polish", "report_mode": "full"}},
    )

    output = result["final_output"]
    assert "Według L3" not in output
    assert "Według źródła lewicowego nr 3" in output
    assert "[Źródło lewicowe nr 3: Siły Zbrojne Ukrainy" in output
