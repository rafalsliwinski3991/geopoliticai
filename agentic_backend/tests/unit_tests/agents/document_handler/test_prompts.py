from agents.document_handler.prompts import ANSWER_SYSTEM_PROMPT, REWRITE_SYSTEM_PROMPT


def test_the_answer_prompt_tells_the_model_to_copy_each_excerpts_citation() -> None:
    """The model once wrote the placeholder "[filename, chunk 1]" literally; copying a ready-made citation leaves nothing to invent."""
    # Arrange
    citation_rule = "copying the cite value"

    # Act
    prompt = ANSWER_SYSTEM_PROMPT

    # Assert
    assert citation_rule in prompt


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


def test_the_rewrite_prompt_turns_a_format_request_into_the_previous_question() -> None:
    """The request "napisz mi po polsku" was searched word for word, found page footers, and the document seemed not to cover the topic."""
    # Arrange
    rule = "only asks for a language or a format"
    target = "the previous question"

    # Act
    prompt = REWRITE_SYSTEM_PROMPT

    # Assert
    assert rule in prompt
    assert target in prompt
