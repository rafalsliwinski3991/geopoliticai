import pytest

from agents.document.state import build_initial_document_state
from api.app import CHECKPOINT_SERDE


@pytest.mark.parametrize("query", ["", "   \n\t "], ids=["empty", "only blanks"])
def test_an_empty_question_is_refused(query: str) -> None:
    """A blank question would embed nothing and cost a model call."""
    # Act + Assert
    with pytest.raises(ValueError, match="must not be empty"):
        build_initial_document_state(query, [])


def test_the_question_is_squashed() -> None:
    """Stray whitespace in a pasted question must not reach the rewrite prompt."""
    # Act
    state = build_initial_document_state("  What \n  are   fees?  ", ["earlier"])

    # Assert
    assert state["query"] == "What are fees?"
    assert state["history"] == ["earlier"]


def test_a_document_state_survives_the_checkpoint_serde() -> None:
    """No new type may enter a checkpoint: a chunk is a dict of primitives, so it needs no allow-list entry."""
    # Arrange
    state = build_initial_document_state("What are fees?", ["earlier"])
    state["chunks"] = [{"filename": "a.txt", "index": 1, "text": "Fees."}]

    # Act
    restored = CHECKPOINT_SERDE.loads_typed(CHECKPOINT_SERDE.dumps_typed(state))

    # Assert
    assert restored == state
