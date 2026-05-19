"""Language-keyed UI strings for the streaming API.

Keeps progress labels and error messages out of `api.py` so that adding a
new language is a one-file change and rename-the-node refactors only touch
this module plus `graph.py`.
"""

from __future__ import annotations

_NODE_LABELS_PL: dict[str, str] = {
    "ingest_request": "Przetwarzam zapytanie...",
    "build_research_plan": "Buduję plan badań...",
    "search_left_pool": "Przeszukuję lewicowe źródła...",
    "search_center_pool": "Przeszukuję centrowe źródła...",
    "search_right_pool": "Przeszukuję prawicowe źródła...",
    "search_people_pool": "Przeszukuję profile osób...",
    "left_analyst": "Analizuję perspektywę lewicową...",
    "center_analyst": "Analizuję perspektywę centrową...",
    "right_analyst": "Analizuję perspektywę prawicową...",
    "people_analyst": "Analizuję profile osób...",
    "referee": "Weryfikuję treść raportu...",
    "referee_blocked_summary": "Podsumowuję blokadę...",
    "extract_claims": "Wyodrębniam twierdzenia...",
    "cross_check_facts": "Sprawdzam fakty krzyżowo...",
    "compose_final": "Komponuję raport końcowy...",
    "supervisor": "Finalizuję odpowiedź...",
}

_NODE_LABELS_EN: dict[str, str] = {
    "ingest_request": "Processing query...",
    "build_research_plan": "Building research plan...",
    "search_left_pool": "Searching left-leaning sources...",
    "search_center_pool": "Searching centrist sources...",
    "search_right_pool": "Searching right-leaning sources...",
    "search_people_pool": "Searching people profiles...",
    "left_analyst": "Analyzing left perspective...",
    "center_analyst": "Analyzing centrist perspective...",
    "right_analyst": "Analyzing right perspective...",
    "people_analyst": "Analyzing people profiles...",
    "referee": "Verifying report content...",
    "referee_blocked_summary": "Summarizing block...",
    "extract_claims": "Extracting claims...",
    "cross_check_facts": "Cross-checking facts...",
    "compose_final": "Composing final report...",
    "supervisor": "Finalizing answer...",
}


def progress_labels(infosphere: str) -> dict[str, str]:
    """Return the per-node progress label map for the given infosphere."""
    return _NODE_LABELS_PL if infosphere == "polish" else _NODE_LABELS_EN


def stream_error_messages(infosphere: str) -> tuple[str, str]:
    """Return (empty_response_message, unexpected_error_template) for the infosphere.

    The second element contains `{}` for the exception detail.
    """
    if infosphere == "polish":
        return ("Backend zwrócił pustą odpowiedź.", "Nieoczekiwany błąd: {}")
    return ("Backend returned an empty response.", "Unexpected error: {}")
