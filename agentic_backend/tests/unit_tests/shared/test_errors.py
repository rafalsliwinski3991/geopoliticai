import pytest

from shared.errors import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    QuotaExceededError,
    ResearchLimitError,
    SearchUnavailableError,
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
        (QuotaExceededError, 429),
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
