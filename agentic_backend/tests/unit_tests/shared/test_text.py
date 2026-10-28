from pydantic import BaseModel

from shared.text import CleanText, squash_whitespace


def test_whitespace_runs_become_one_space() -> None:
    # Arrange
    text = "  Spread\t\tout \n\n across   the flank  "

    # Act
    result = squash_whitespace(text)

    # Assert
    assert result == "Spread out across the flank"


def test_a_clean_text_field_arrives_squashed() -> None:
    # Arrange
    class Note(BaseModel):
        text: CleanText

    # Act
    note = Note.model_validate({"text": "  one \n two  "})

    # Assert
    assert note.text == "one two"
