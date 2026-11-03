"""Query rewrite, embedding, and nearest-chunk search (graph node 1)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from pydantic import BaseModel

from agents.document_handler.config import RETRIEVAL, REWRITE_LLM_SETTINGS
from agents.document_handler.prompts import REWRITE_SYSTEM_PROMPT
from agents.document_handler.state import DocumentContext, DocumentState
from services.embeddings import embed_query
from services.llm import ainvoke_structured
from shared.errors import LLMInvocationError, NoDocumentError
from shared.text import squash_whitespace
from shared.tracing import start_span


class RewrittenQuery(BaseModel):
    """The model's reply: the search query, the language of the latest message, and how much to read."""

    search_query: str
    language: Literal["pl", "en"]
    scope: Literal["passages", "whole"]


def _rewrite_input(state: DocumentState) -> str:
    earlier = "\n".join(state["history"][-RETRIEVAL.history_messages :])
    return f"Earlier messages:\n{earlier}\n\nLatest message:\n{state['query']}"


async def retrieve(
    state: DocumentState,
    runtime: Runtime[DocumentContext],
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """Rewrite the question, embed it, and read the nearest chunks of the thread."""
    with start_span("document_search") as span:
        span.set_attribute("document.query", state["query"])
        rewritten = await ainvoke_structured(
            REWRITE_SYSTEM_PROMPT,
            [HumanMessage(_rewrite_input(state))],
            RewrittenQuery,
            config=config,
            settings=REWRITE_LLM_SETTINGS,
        )
        search_query = squash_whitespace(rewritten.search_query)
        span.set_attribute("document.search_query", search_query)
        span.set_attribute("document.rewrite_model", REWRITE_LLM_SETTINGS.model)
        span.set_attribute("document.language", rewritten.language)
        if not search_query:
            raise LLMInvocationError("The rewrite returned an empty search query.")
        span.set_attribute("document.scope", rewritten.scope)
        limit = (
            RETRIEVAL.whole_chunks
            if rewritten.scope == "whole"
            else RETRIEVAL.top_chunks
        )
        chunks = await runtime.context.search(await embed_query(search_query), limit)
        if rewritten.scope == "whole":
            chunks = sorted(chunks, key=lambda chunk: chunk["index"])
        span.set_attribute("document.chunks", len(chunks))
        if not chunks:
            raise NoDocumentError("This conversation has no document to search.")
    return {
        "search_query": search_query,
        "language": rewritten.language,
        "chunks": chunks,
    }
