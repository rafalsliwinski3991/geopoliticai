"""Unit tests for the pure part of db/agentic/chunks.py; the SQL is in the integration tests."""

from db.agentic.chunks import format_vector


def test_a_vector_is_written_as_a_bracketed_list() -> None:
    """pgvector parses `[a,b,c]` text, and the pool registers no adapter, so
    the vector must reach the database in exactly this form."""
    # Arrange
    values = [0.1, -2.5, 3.0]

    # Act
    text = format_vector(values)

    # Assert
    assert text == "[0.1,-2.5,3.0]"


def test_a_vector_keeps_small_exponents() -> None:
    """A tiny component printed as 0.0 would silently change the embedding."""
    # Arrange
    values = [2.5e-05, -1e-07]

    # Act
    text = format_vector(values)

    # Assert
    assert text == "[2.5e-05,-1e-07]"
