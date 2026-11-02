"""OpenAI embeddings boundary: one batch of texts, or one query."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from shared.errors import LLMInvocationError

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_TIMEOUT_SECONDS = 30.0
EMBEDDING_MAX_RETRIES = 1
EMBEDDING_BATCH_SIZE = 128


def _build_embeddings() -> OpenAIEmbeddings:
    # Our chunks are already at most 800 tokens, so the client's own pass that
    # re-tokenises every text (on the event loop) is turned off.
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        timeout=EMBEDDING_TIMEOUT_SECONDS,
        max_retries=EMBEDDING_MAX_RETRIES,
        chunk_size=EMBEDDING_BATCH_SIZE,
        check_embedding_ctx_length=False,
    )


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one vector per text, in order; a provider failure is a 502."""
    if not texts:
        return []
    try:
        vectors = await _build_embeddings().aembed_documents(texts)
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Embedding call failed.") from exc
    if len(vectors) != len(texts):
        raise LLMInvocationError("Embedding call returned the wrong number of vectors.")
    return vectors


async def embed_query(text: str) -> list[float]:
    """Return the vector for one search query."""
    try:
        return await _build_embeddings().aembed_query(text)
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Embedding call failed.") from exc
