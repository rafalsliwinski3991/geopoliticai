"""The client against a real `mcp-server`; needs one running at `SANDBOX_MCP_URL`."""

import pytest

from services.code_sandbox import run_code


@pytest.mark.anyio
async def test_the_adapter_client_runs_code_on_the_real_sandbox() -> None:
    """The client is on `mcp` 1.x and the server on 2.x; only a real call shows
    that the two still agree on the protocol and the result's shape."""
    # Arrange
    code = "print(1 + 1)"

    # Act
    run = await run_code(code)

    # Assert
    assert (run.outcome, run.stdout) == ("ok", "2\n")
