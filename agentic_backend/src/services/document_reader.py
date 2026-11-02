"""Read an uploaded document into text and split the text into chunks."""

from __future__ import annotations

import asyncio
import io

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


def _read_pdf(body: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(body))
        if len(reader.pages) > MAX_DOCUMENT_PAGES:
            raise DocumentTooLargeError(
                f"That PDF has more than {MAX_DOCUMENT_PAGES} pages."
            )
        return PARAGRAPH_BREAK.join(page.extract_text() or "" for page in reader.pages)
    except DocumentTooLargeError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on bad input
        raise DocumentUnreadableError(UNREADABLE_MESSAGE) from exc


def _read_text(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentUnreadableError("That text file is not UTF-8.") from exc


async def read_document(body: bytes, filename: str) -> str:
    """Return the file's text; raise when it is too big, the wrong type, or empty."""
    if len(body) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError("That file is over 25 MB.")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "pdf":
        text = await asyncio.to_thread(_read_pdf, body)
    elif suffix == "txt":
        text = _read_text(body)
    else:
        raise DocumentUnreadableError("Upload a PDF or a .txt file.")
    if "\x00" in text:
        raise DocumentUnreadableError("That file contains NUL bytes.")
    if not text.strip():
        raise DocumentUnreadableError(UNREADABLE_MESSAGE)
    if len(text) > MAX_DOCUMENT_CHARS:
        raise DocumentTooLargeError("That file is too long to read.")
    return text


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


def _take_overlap(current: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Return the trailing pieces of a finished chunk that fit the overlap."""
    tail: list[tuple[str, int]] = []
    total = 0
    for piece, cost in reversed(current):
        if total + cost > OVERLAP_TOKENS:
            break
        tail.insert(0, (piece, cost))
        total += cost
    return tail


def split_into_chunks(text: str) -> list[str]:
    """Pack paragraphs into chunks of at most `CHUNK_TOKENS` tokens.

    Each chunk after the first starts with the closing paragraphs of the one
    before, up to `OVERLAP_TOKENS`, so a sentence cut at a boundary is whole in
    one of the two chunks. A paragraph longer than `CHUNK_TOKENS - OVERLAP_TOKENS`
    is cut at word boundaries (never mid-character, which a token cut can do to
    Polish text). Synchronous and CPU-bound: callers on the event loop use
    `asyncio.to_thread`. A single word longer than a chunk stays whole.
    """
    encoding = tiktoken.get_encoding(TOKEN_ENCODING)
    budget = CHUNK_TOKENS - OVERLAP_TOKENS
    pieces: list[str] = []
    for paragraph in text.split(PARAGRAPH_BREAK):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if _count_tokens(encoding, paragraph) <= budget:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_at_words(encoding, paragraph, budget))
    chunks: list[str] = []
    current: list[tuple[str, int]] = []
    size = 0
    for piece in pieces:
        cost = _count_tokens(encoding, piece)
        if current and size + cost > CHUNK_TOKENS:
            chunks.append(PARAGRAPH_BREAK.join(text for text, _ in current))
            current = _take_overlap(current)
            size = sum(tokens for _, tokens in current)
        current.append((piece, cost))
        size += cost
    if current:
        chunks.append(PARAGRAPH_BREAK.join(text for text, _ in current))
    return chunks
