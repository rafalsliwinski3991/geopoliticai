"""document_handler_fixed eval: the document agent answers from one synthetic report."""

from __future__ import annotations

import asyncio
from typing import Any

from agents.document_handler.config import RETRIEVAL
from agents.document_handler.state import Chunk
from evals.helpers.graph import load_document, load_messages, rank_by_cosine
from evals.helpers.run import run
from evals.judges.document_handler_fixed import judges
from services.document_reader import Page, split_into_chunks
from services.embeddings import embed_texts


async def run_document_handler_fixed(input: dict[str, Any]) -> dict[str, Any]:
    """Answer one question from the case's document, searched in memory with real embeddings."""
    from agents.document_handler.graph import ask_document

    filename, text = load_document(input["document"])
    chunks = split_into_chunks([Page(None, text)])
    texts = [chunk.text for chunk in chunks]
    vectors = await embed_texts(texts)

    async def search(embedding: list[float]) -> list[Chunk]:
        nearest = rank_by_cosine(embedding, vectors, RETRIEVAL.top_chunks)
        return [
            Chunk(
                filename=filename,
                index=position + 1,
                page_start=chunks[position].page_start,
                page_end=chunks[position].page_end,
                text=texts[position],
            )
            for position in nearest
        ]

    # The production history format: `human: ...` and `ai: ...` lines.
    history = [
        f"{message.type}: {message.content}"
        for message in load_messages(input.get("messages", []))
    ]
    result = await ask_document(input["query"], history, search)
    return {"answer": result["answer"], "search_query": result["search_query"]}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="document_handler_fixed",
            task=run_document_handler_fixed,
            judges=judges(),
        )
    )
