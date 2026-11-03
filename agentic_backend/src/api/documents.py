"""Upload and remove a thread's document; build the per-run document context."""

from __future__ import annotations

import asyncio
import functools
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from agents.document_handler import Chunk
from agents.orchestrator.state import OrchestratorContext
from api.auth import Identity, require_identity
from api.rate_limit import enforce_rate_limit, enforce_upload_limit
from api.routes import ThreadIdPath
from db.agentic.chunks import (
    count_live_documents,
    delete_chunks,
    read_document_name,
    replace_chunks,
    search_chunks,
)
from db.web.sql import claim_thread, owns_thread, title_from
from services.document_reader import read_document, split_into_chunks
from services.embeddings import embed_texts
from shared.config import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHUNKS,
    MAX_DOCUMENTS_PER_USER,
    bind_log_context,
)
from shared.errors import (
    DocumentLimitError,
    DocumentTooLargeError,
    DocumentUnreadableError,
    ResearchLimitError,
)
from shared.tracing import bind_trace_user, start_span

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

MAX_FILENAME_LENGTH = 100
DISALLOWED_FILENAME_CHARACTERS = re.compile(r"[^\w.() -]")
# One upload must finish well inside nginx's 600 s read timeout, so a request the
# client has already seen fail cannot go on to commit its chunks.
EMBED_WALL_SECONDS = 120.0


class DocumentView(BaseModel):
    """The document now attached to a thread."""

    filename: str
    chunks: int


def clean_filename(raw: str) -> str:
    """Return a name safe to show, store, and put in a prompt wrapper.

    Keeps the base name, letters, digits, dots, spaces, brackets and dashes, and
    at most `MAX_FILENAME_LENGTH` characters with the extension intact.
    """
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = DISALLOWED_FILENAME_CHARACTERS.sub("_", base).strip(" .") or "document"
    if len(cleaned) <= MAX_FILENAME_LENGTH:
        return cleaned
    stem, dot, suffix = cleaned.rpartition(".")
    if not dot or len(suffix) > 10:
        return cleaned[:MAX_FILENAME_LENGTH]
    return stem[: MAX_FILENAME_LENGTH - len(suffix) - 1] + "." + suffix


async def read_body(request: Request) -> bytes:
    """Read the request body, refusing at `MAX_DOCUMENT_BYTES` without buffering past it."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError("That file is over 25 MB.")
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > MAX_DOCUMENT_BYTES:
            raise DocumentTooLargeError("That file is over 25 MB.")
    return bytes(body)


async def ingest_document(
    pool: Pool, *, thread_id: str, user_id: int, filename: str, body: bytes
) -> DocumentView:
    """Read, chunk, embed, and store a file, replacing the thread's earlier one.

    Nothing is written until everything that can fail has succeeded, and the
    thread row is claimed last: a refused upload leaves no empty conversation
    and keeps the old document. The cap is checked first so a refused upload
    costs no embedding; it is not atomic with the insert, so concurrent uploads
    from one user can overshoot it by as many as the upload rate limit lets
    start, which only costs storage.
    """
    with start_span("document_ingest") as span:
        span.set_attribute("document.bytes", len(body))
        if (
            await count_live_documents(pool, user_id=user_id, thread_id=thread_id)
            >= MAX_DOCUMENTS_PER_USER
        ):
            span.set_attribute("document.outcome", "limit")
            raise DocumentLimitError(
                f"You can keep {MAX_DOCUMENTS_PER_USER} documents. "
                "Remove one from an older conversation first."
            )
        try:
            pages = await read_document(body, filename)
        except DocumentUnreadableError:
            span.set_attribute("document.outcome", "unreadable")
            raise
        except DocumentTooLargeError:
            span.set_attribute("document.outcome", "too_large")
            raise
        chunks = await asyncio.to_thread(split_into_chunks, pages)
        span.set_attribute("document.chunks", len(chunks))
        if len(chunks) > MAX_DOCUMENT_CHUNKS:
            span.set_attribute("document.outcome", "too_large")
            raise DocumentTooLargeError("That file is too long to read.")
        try:
            async with asyncio.timeout(EMBED_WALL_SECONDS):
                embeddings = await embed_texts([chunk.text for chunk in chunks])
        except TimeoutError as exc:
            span.set_attribute("document.outcome", "timeout")
            raise ResearchLimitError("Reading the document took too long.") from exc
        if not await claim_thread(
            pool, thread_id=thread_id, user_id=user_id, title=title_from(filename)
        ):
            span.set_attribute("document.outcome", "foreign_thread")
            raise HTTPException(
                status_code=403, detail="That conversation is not yours."
            )
        await replace_chunks(
            pool,
            thread_id=thread_id,
            user_id=user_id,
            filename=filename,
            texts=[chunk.text for chunk in chunks],
            pages=[(chunk.page_start, chunk.page_end) for chunk in chunks],
            embeddings=embeddings,
        )
        span.set_attribute("document.outcome", "stored")
    return DocumentView(filename=filename, chunks=len(chunks))


async def _search_chunks(
    pool: Pool, thread_id: str, user_id: int, embedding: list[float], limit: int
) -> list[Chunk]:
    rows = await search_chunks(
        pool,
        thread_id=thread_id,
        user_id=user_id,
        embedding=embedding,
        limit=limit,
    )
    return [
        {
            "filename": row["filename"],
            "index": row["chunk_index"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "text": row["content"],
        }
        for row in rows
    ]


async def build_orchestrator_context(
    pool: Pool, *, thread_id: str, user_id: int
) -> OrchestratorContext:
    """Return the run context: the thread's document and a search over it, if any."""
    filename = await read_document_name(pool, thread_id=thread_id, user_id=user_id)
    if filename is None:
        return OrchestratorContext()
    return OrchestratorContext(
        filename=filename,
        search_document=functools.partial(_search_chunks, pool, thread_id, user_id),
    )


@router.post("/threads/{thread_id}/document")
async def upload_document_endpoint(
    thread_id: ThreadIdPath,
    request: Request,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
    identity: Identity = Depends(require_identity),
) -> DocumentView:
    """Attach a file to the caller's conversation, creating it when it is new.

    The body is the raw file. It is read only after the caller is authenticated
    and rate-limited, which a multipart parameter would not allow.
    """
    bind_log_context(thread_id=thread_id, user_id=identity.user_id)
    bind_trace_user(identity.user_id)
    enforce_rate_limit(request, identity)
    enforce_upload_limit(identity)
    body = await read_body(request)
    return await ingest_document(
        request.app.state.pool,
        thread_id=thread_id,
        user_id=identity.user_id,
        filename=clean_filename(filename),
        body=body,
    )


@router.delete("/threads/{thread_id}/document", status_code=204)
async def remove_document_endpoint(
    thread_id: ThreadIdPath,
    request: Request,
    identity: Identity = Depends(require_identity),
) -> Response:
    """Remove the conversation's document. Removing nothing is still a success."""
    bind_log_context(thread_id=thread_id, user_id=identity.user_id)
    enforce_rate_limit(request, identity)
    pool: Pool = request.app.state.pool
    if not await owns_thread(pool, thread_id=thread_id, user_id=identity.user_id):
        raise HTTPException(status_code=403, detail="That conversation is not yours.")
    await delete_chunks(pool, thread_id=thread_id, user_id=identity.user_id)
    return Response(status_code=204)
