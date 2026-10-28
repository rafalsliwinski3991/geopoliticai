from models import Source


def test_a_source_defaults_to_no_author() -> None:
    # Act + Assert
    assert Source("t", "u", "x").author == ""
