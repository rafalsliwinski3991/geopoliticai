import pytest

from agents.expert.state import PipelineState, build_initial_pipeline_state

POLISH_QUERY = " Co robi NATO? "
ENGLISH_SEARCH_QUERY = "  What   is NATO doing? "


@pytest.mark.parametrize(
    "blank_search_query",
    [None, "", "   "],
    ids=["omitted", "empty", "whitespace only"],
)
def test_build_initial_pipeline_state_defaults_search_query_to_query_when_omitted_or_blank(
    blank_search_query: str | None,
) -> None:
    """Without an English search query the expert still searches with the question itself."""
    # Arrange
    expected: PipelineState = {
        "query": "Co robi NATO?",
        "search_query": "Co robi NATO?",
        "sources": [],
        "answer": "",
    }

    # Act
    state = build_initial_pipeline_state(POLISH_QUERY, search_query=blank_search_query)

    # Assert
    assert state == expected


def test_build_initial_pipeline_state_normalizes_explicit_search_query() -> None:
    """Stray whitespace from the model must not reach the Brave query."""
    # Arrange
    query = "Co robi NATO?"

    # Act
    state = build_initial_pipeline_state(query, search_query=ENGLISH_SEARCH_QUERY)

    # Assert
    assert state["search_query"] == "What is NATO doing?"


@pytest.mark.parametrize("empty_query", ["", "   "], ids=["empty", "whitespace only"])
def test_build_initial_pipeline_state_rejects_empty_query(empty_query: str) -> None:
    """A search query cannot stand in for a missing question."""
    # Act + Assert
    with pytest.raises(ValueError, match="Query must not be empty."):
        build_initial_pipeline_state(empty_query, search_query="What is NATO?")
