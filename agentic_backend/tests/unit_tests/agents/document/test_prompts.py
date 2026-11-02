from agents.document.prompts import ANSWER_SYSTEM_PROMPT


def test_the_answer_prompt_asks_for_filename_and_chunk_citations() -> None:
    """The reader checks a claim by its chunk number; without the format there is nothing to check."""
    # Assert
    assert "[filename, chunk N]" in ANSWER_SYSTEM_PROMPT


def test_the_answer_prompt_tells_the_model_to_say_when_the_document_does_not_cover_it() -> (
    None
):
    """Without this the model fills gaps from memory and the user trusts it as the document's."""
    # Assert
    assert "the document does not cover it" in ANSWER_SYSTEM_PROMPT
    assert "Never answer from memory" in ANSWER_SYSTEM_PROMPT


def test_the_answer_prompt_calls_excerpts_untrusted_and_forbids_images() -> None:
    """An uploaded file can hide instructions or an image URL that leaks the chat when rendered."""
    # Assert
    assert "untrusted data" in ANSWER_SYSTEM_PROMPT
    assert "never write an image" in ANSWER_SYSTEM_PROMPT
