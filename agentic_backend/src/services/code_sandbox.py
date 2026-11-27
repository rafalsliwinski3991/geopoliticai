"""The code sandbox (`mcp_server/`) over MCP: one `run_python` call per `run_code`.

A run that fails inside the sandbox (a bug, a timeout, out of memory, a refusal)
is a normal `CodeRun` the model can act on. An unreachable sandbox, a server
fault (`isError`), or a malformed result raises (brainstorm Q13): a deep turn
never answers with numbers it meant to compute and could not.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import timedelta

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.shared.exceptions import McpError
from mcp.types import TextContent

from shared.errors import SandboxUnavailableError

SANDBOX_URL_ENV = "SANDBOX_MCP_URL"
DEFAULT_SANDBOX_URL = "http://mcp-server:8000/mcp"
SANDBOX_SERVER = "sandbox"
RUN_TOOL = "run_python"
# The server's 15 s queue wait plus its 10 s run, plus margin.
CALL_TIMEOUT_SECONDS = 40.0
UNAVAILABLE_MESSAGE = "The code sandbox is unavailable."
RESULT_FIELDS = (
    "outcome",
    "stdout",
    "stderr",
    "exit_code",
    "truncated",
    "duration_ms",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeRun:
    """One run as the client sees it."""

    outcome: str
    stdout: str
    stderr: str
    exit_code: int | None
    truncated: bool
    duration_ms: int


async def run_code(code: str) -> CodeRun:
    """Run `code` in the sandbox; raise `SandboxUnavailableError` if it cannot answer."""
    url = os.getenv(SANDBOX_URL_ENV) or DEFAULT_SANDBOX_URL
    timeout = timedelta(seconds=CALL_TIMEOUT_SECONDS)
    client = MultiServerMCPClient(
        {
            SANDBOX_SERVER: {
                "transport": "streamable_http",
                "url": url,
                "timeout": timeout,
                "sse_read_timeout": timeout,
            }
        }
    )
    try:
        async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
            async with client.session(SANDBOX_SERVER) as session:
                result = await session.call_tool(RUN_TOOL, {"code": code})
    # A refused connection arrives as ExceptionGroup([httpx.ConnectError]), and so
    # does everything raised inside the session, nested in a second group: the
    # RuntimeError the mcp 1.x client raises when structured output fails its
    # schema included (verified against mcp 1.30 / adapters 0.3.2).
    # CancelledError (the deep expert's wall cap) is deliberately not caught.
    except (
        OSError,
        TimeoutError,
        RuntimeError,
        httpx.HTTPError,
        McpError,
        ExceptionGroup,
    ) as exc:
        logger.warning("code sandbox unreachable at %s: %r", url, exc)
        raise SandboxUnavailableError(UNAVAILABLE_MESSAGE) from exc
    if result.isError:
        detail = " ".join(b.text for b in result.content if isinstance(b, TextContent))
        logger.warning("code sandbox server fault: %s", detail)
        raise SandboxUnavailableError(UNAVAILABLE_MESSAGE)
    data = result.structuredContent
    if not isinstance(data, dict) or any(key not in data for key in RESULT_FIELDS):
        raise SandboxUnavailableError("The code sandbox returned no usable result.")
    return CodeRun(**{key: data[key] for key in RESULT_FIELDS})
