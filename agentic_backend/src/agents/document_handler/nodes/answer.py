"""Answer composition from the retrieved chunks (graph node 2)."""

from __future__ import annotations

import re
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from agents.document_handler.config import ANSWER_LLM_SETTINGS
from agents.document_handler.prompts import ANSWER_SYSTEM_PROMPT
from agents.document_handler.state import Chunk, DocumentState
from services.llm import astream_text, collect_text

# A chunk that contains the closing tag would end its own wrapper early.
CLOSING_TAG = re.compile(r"</\s*excerpt", re.IGNORECASE)
ESCAPED_CLOSING_TAG = "<\\/excerpt"
LANGUAGE_NAMES = {"pl": "Polish", "en": "English"}


def _citation(chunk: Chunk) -> str:
    """Return the citation the model copies: pages when the chunk has them, else its number."""
    start, end = chunk["page_start"], chunk["page_end"]
    if start is None or end is None:
        place = f"chunk {chunk['index']}"
    elif start == end:
        place = f"p. {start}"
    else:
        place = f"pp. {start}-{end}"
    return f"[{chunk['filename']}, {place}]"


def _excerpt(chunk: Chunk) -> str:
    text = CLOSING_TAG.sub(ESCAPED_CLOSING_TAG, chunk["text"])
    return f'<excerpt cite="{_citation(chunk)}">\n{text}\n</excerpt>'


def _excerpts_block(chunks: list[Chunk]) -> str:
    return "\n\n".join(_excerpt(chunk) for chunk in chunks)


async def answer(
    state: DocumentState, config: Optional[RunnableConfig] = None
) -> dict[str, Any]:
    """Write the cited answer from the excerpts in one streamed call."""
    human_prompt = (
        f"Answer in {LANGUAGE_NAMES[state['language']]}.\n\n"
        f"Question: {state['query']}\n\nExcerpts:\n\n{_excerpts_block(state['chunks'])}"
    )
    text = await collect_text(
        astream_text(
            ANSWER_SYSTEM_PROMPT,
            human_prompt,
            config=config,
            settings=ANSWER_LLM_SETTINGS,
        )
    )
    return {"answer": text}
