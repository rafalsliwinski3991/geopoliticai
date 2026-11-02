"""The document agent's state and its per-run context."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from pydantic.json_schema import SkipJsonSchema
from typing_extensions import TypedDict

from shared.text import squash_whitespace


class Chunk(TypedDict):
    """One retrieved excerpt. `index` counts from 1 within the document."""

    filename: str
    index: int
    text: str


# Embedding in, nearest chunks out. `api` builds it over `db`; agents never import `db`.
DocumentSearch = Callable[[list[float]], Awaitable[list[Chunk]]]


@dataclass(frozen=True)
class DocumentContext:
    """What a run needs that is not graph state."""

    search: Annotated[DocumentSearch, SkipJsonSchema()]


class DocumentState(TypedDict):
    """What flows between the two nodes of one question."""

    query: str
    history: list[str]
    search_query: str
    chunks: list[Chunk]
    answer: str


def build_initial_document_state(query: str, history: list[str]) -> DocumentState:
    """Return the input for one question."""
    normalized = squash_whitespace(query or "")
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {
        "query": normalized,
        "history": history,
        "search_query": "",
        "chunks": [],
        "answer": "",
    }
