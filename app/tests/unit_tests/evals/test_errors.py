import pytest

from evals.errors import InvalidRunError


def test_invalid_run_error_is_not_a_pipeline_error() -> None:
    from models import PipelineError

    assert not issubclass(InvalidRunError, PipelineError)
    with pytest.raises(InvalidRunError):
        raise InvalidRunError("phoenix unreachable")
