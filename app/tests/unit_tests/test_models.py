import pytest

from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    SearchUnavailableError,
)


def test_llm_invocation_error_is_a_pipeline_error() -> None:
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
    assert error_type.status == status
