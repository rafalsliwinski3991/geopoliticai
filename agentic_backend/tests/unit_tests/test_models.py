import ormsgpack
import pytest
from langgraph.checkpoint.serde.jsonplus import EXT_CONSTRUCTOR_KW_ARGS
from pydantic import BaseModel

import api
from models import (
    CleanText,
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    ResearchLimitError,
    SearchUnavailableError,
    Source,
    squash_whitespace,
)


def test_llm_invocation_error_is_a_pipeline_error() -> None:
    # Assert
    assert issubclass(LLMInvocationError, PipelineError)


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (PipelineError, 500),
        (NoSourcesError, 422),
        (SearchUnavailableError, 503),
        (LLMInvocationError, 502),
    ],
)
def test_each_error_carries_its_status(
    error_type: type[PipelineError], status: int
) -> None:
    # Act + Assert
    assert error_type.status == status


def test_research_limit_error_is_a_pipeline_error() -> None:
    # Assert
    assert issubclass(ResearchLimitError, PipelineError)


def test_research_limit_error_status_is_504() -> None:
    # Act + Assert
    assert ResearchLimitError.status == 504


def test_a_source_defaults_to_no_author() -> None:
    # Act + Assert
    assert Source("t", "u", "x").author == ""


def test_a_checkpointed_source_without_author_still_loads() -> None:
    # Arrange: the payload as the serde wrote a three-field `Source` before
    # `author` existed, rebuilt with dataclass keyword loading.
    payload = ormsgpack.packb(
        ormsgpack.Ext(
            EXT_CONSTRUCTOR_KW_ARGS,
            ormsgpack.packb(
                ("models", "Source", {"title": "t", "url": "u", "text": "x"})
            ),
        )
    )
    # Act
    loaded = api.CHECKPOINT_SERDE.loads_typed(("msgpack", payload))
    # Assert
    assert isinstance(loaded, Source)
    assert loaded == Source(title="t", url="u", text="x", author="")


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
