import importlib
from typing import Any, AsyncIterator

import pytest

from models import NoSourcesError, Source

answer_module = importlib.import_module("agents.expert.nodes.answer")


def test_sources_block_has_no_ids() -> None:
    block = answer_module._sources_block(
        [Source("Reuters", "https://reuters.com/x", "body")]
    )
    assert "--- SOURCE ---" in block and "SOURCE 1" not in block and "[1]" not in block


def test_braces_survive_prompt() -> None:
    assert '{"a": 1}' in answer_module._sources_block(
        [Source("t", "https://bbc.com/x", '{"a": 1}')]
    )


@pytest.mark.anyio
async def test_no_sources_raises() -> None:
    with pytest.raises(NoSourcesError):
        await answer_module.answer({"query": "x", "sources": [], "answer": ""})


@pytest.mark.anyio
async def test_stream_chunks_join(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stream(
        system_prompt: str,
        human_prompt: str,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        yield "Hello "
        yield "world."

    monkeypatch.setattr(answer_module, "astream_text", stream)
    state = {
        "query": "x",
        "sources": [Source("t", "https://bbc.com/x", "body")],
        "answer": "",
    }
    assert await answer_module.answer(state) == {"answer": "Hello world."}
