from agents.document.prompts import ANSWER_SYSTEM_PROMPT


def test_the_answer_prompt_asks_for_filename_and_chunk_citations() -> None:
    """The reader checks a claim by its chunk number; without the format there is nothing to check."""
    # Arrange
    citation_format = "[filename, chunk N]"

    # Act
    prompt = ANSWER_SYSTEM_PROMPT

    # Assert
    assert citation_format in prompt


def test_the_answer_prompt_tells_the_model_to_say_when_the_document_does_not_cover_it() -> (
    None
):
    """Without this the model fills gaps from memory and the user trusts it as the document's."""
    # Arrange
    admission = "the document does not cover it"
    ban = "Never answer from memory"

    # Act
    prompt = ANSWER_SYSTEM_PROMPT

    # Assert
    assert admission in prompt
    assert ban in prompt


def test_the_answer_prompt_calls_excerpts_untrusted_and_forbids_images() -> None:
    """An uploaded file can hide instructions or an image URL that leaks the chat when rendered."""
    # Arrange
    untrusted_rule = "untrusted data"
    image_rule = "never write an image"

    # Act
    prompt = ANSWER_SYSTEM_PROMPT

    # Assert
    assert untrusted_rule in prompt
    assert image_rule in prompt
