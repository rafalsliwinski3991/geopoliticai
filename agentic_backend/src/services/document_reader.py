"""Read an uploaded document into text and split the text into chunks."""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import tiktoken
from pypdf import PdfReader

from shared.config import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHUNKS,
    MAX_DOCUMENT_PAGES,
)
from shared.errors import DocumentTooLargeError, DocumentUnreadableError

CHUNK_TOKENS = 800
OVERLAP_TOKENS = 100
CHARS_PER_TOKEN = 4
# Text past this many characters cannot fit `MAX_DOCUMENT_CHUNKS` chunks, so it is
# refused before the chunker spends time on it.
MAX_DOCUMENT_CHARS = MAX_DOCUMENT_CHUNKS * CHUNK_TOKENS * CHARS_PER_TOKEN
# The encoding `text-embedding-3-small` uses, so chunk sizes match what is embedded.
TOKEN_ENCODING = "cl100k_base"
PARAGRAPH_BREAK = "\n\n"
UNREADABLE_MESSAGE = "That file has no readable text."


@dataclass(frozen=True)
class Page:
    """One page of a document. `number` counts from 1; a text file is one page with none."""

    number: int | None
    text: str


@dataclass(frozen=True)
class TextChunk:
    """A chunk and the first and last page it came from (`None` for a text file)."""

    text: str
    page_start: int | None
    page_end: int | None


def _read_pdf(body: bytes) -> list[Page]:
    try:
        reader = PdfReader(io.BytesIO(body))
        if len(reader.pages) > MAX_DOCUMENT_PAGES:
            raise DocumentTooLargeError(
                f"That PDF has more than {MAX_DOCUMENT_PAGES} pages."
            )
        return [
            Page(number, page.extract_text() or "")
            for number, page in enumerate(reader.pages, start=1)
        ]
    except DocumentTooLargeError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on bad input
        raise DocumentUnreadableError(UNREADABLE_MESSAGE) from exc


def _read_text(body: bytes) -> list[Page]:
    try:
        return [Page(None, body.decode("utf-8"))]
    except UnicodeDecodeError as exc:
        raise DocumentUnreadableError("That text file is not UTF-8.") from exc


async def read_document(body: bytes, filename: str) -> list[Page]:
    """Return the file's pages; raise when it is too big, the wrong type, or empty."""
    if len(body) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError("That file is over 25 MB.")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "pdf":
        pages = await asyncio.to_thread(_read_pdf, body)
    elif suffix == "txt":
        pages = _read_text(body)
    else:
        raise DocumentUnreadableError("Upload a PDF or a .txt file.")
    text = PARAGRAPH_BREAK.join(page.text for page in pages)
    if "\x00" in text:
        raise DocumentUnreadableError("That file contains NUL bytes.")
    if not text.strip():
        raise DocumentUnreadableError(UNREADABLE_MESSAGE)
    if len(text) > MAX_DOCUMENT_CHARS:
        raise DocumentTooLargeError("That file is too long to read.")
    return pages


def _count_tokens(encoding: tiktoken.Encoding, text: str) -> int:
    return len(encoding.encode(text))


def _split_at_words(
    encoding: tiktoken.Encoding, paragraph: str, budget: int
) -> list[str]:
    """Cut one paragraph that is over `budget` tokens at word boundaries."""
    pieces: list[str] = []
    words: list[str] = []
    size = 0
    for word in paragraph.split():
        cost = _count_tokens(encoding, word) + 1
        if words and size + cost > budget:
            pieces.append(" ".join(words))
            words, size = [], 0
        words.append(word)
        size += cost
    if words:
        pieces.append(" ".join(words))
    return pieces


def _take_overlap(
    current: list[tuple[str, int, int | None]],
) -> list[tuple[str, int, int | None]]:
    """Return the trailing pieces of a finished chunk that fit the overlap."""
    tail: list[tuple[str, int, int | None]] = []
    total = 0
    for piece, cost, page in reversed(current):
        if total + cost > OVERLAP_TOKENS:
            break
        tail.insert(0, (piece, cost, page))
        total += cost
    return tail


def _build_chunk(current: list[tuple[str, int, int | None]]) -> TextChunk:
    """Join the pieces of one chunk and record the first and last page among them."""
    numbers = [page for _, _, page in current if page is not None]
    return TextChunk(
        text=PARAGRAPH_BREAK.join(piece for piece, _, _ in current),
        page_start=numbers[0] if numbers else None,
        page_end=numbers[-1] if numbers else None,
    )


def split_into_chunks(pages: list[Page]) -> list[TextChunk]:
    """Pack paragraphs into chunks of at most `CHUNK_TOKENS` tokens.

    Each chunk after the first starts with the closing paragraphs of the one
    before, up to `OVERLAP_TOKENS`, so a sentence cut at a boundary is whole in
    one of the two chunks. A paragraph longer than `CHUNK_TOKENS - OVERLAP_TOKENS`
    is cut at word boundaries (never mid-character, which a token cut can do to
    Polish text). Chunks ignore page breaks; each records the first and last page
    of the text in it, the repeated overlap included. Synchronous and CPU-bound:
    callers on the event loop use `asyncio.to_thread`. A single word longer than
    a chunk stays whole.
    """
    encoding = tiktoken.get_encoding(TOKEN_ENCODING)
    budget = CHUNK_TOKENS - OVERLAP_TOKENS
    pieces: list[tuple[str, int | None]] = []
    for page in pages:
        for paragraph in page.text.split(PARAGRAPH_BREAK):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if _count_tokens(encoding, paragraph) <= budget:
                pieces.append((paragraph, page.number))
            else:
                pieces.extend(
                    (piece, page.number)
                    for piece in _split_at_words(encoding, paragraph, budget)
                )
    chunks: list[TextChunk] = []
    current: list[tuple[str, int, int | None]] = []
    size = 0
    for piece, page_number in pieces:
        cost = _count_tokens(encoding, piece)
        if current and size + cost > CHUNK_TOKENS:
            chunks.append(_build_chunk(current))
            current = _take_overlap(current)
            size = sum(tokens for _, tokens, _ in current)
        current.append((piece, cost, page_number))
        size += cost
    if current:
        chunks.append(_build_chunk(current))
    return chunks
