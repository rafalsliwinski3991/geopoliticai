import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import tiktoken
from pypdf import PdfReader, PdfWriter

from services import document_reader
from services.document_reader import CHUNK_TOKENS, read_document, split_into_chunks
from shared.errors import DocumentTooLargeError, DocumentUnreadableError

PARAGRAPH_BREAK = "\n\n"
PAGE_CAP = 2
LONG_WORD = "x" * 40_000


def _words(count: int) -> str:
    """Return `count` copies of one word that costs exactly one token each."""
    return " ".join(["word"] * count)


def _text_pdf(pages: int, text: str = "Hello PDF") -> bytes:
    """Build a small valid PDF whose every page shows `text`."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i in range(pages):
        stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET"
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return out


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# --- split_into_chunks ---


@pytest.mark.parametrize(
    "text",
    ["", f"  {PARAGRAPH_BREAK}   {PARAGRAPH_BREAK}"],
    ids=["empty", "only blanks"],
)
def test_empty_text_makes_no_chunks(text: str) -> None:
    """A chunk with no words would be embedded and paid for, then match nothing."""
    # Arrange
    raw_text = text

    # Act
    chunks = split_into_chunks(raw_text)

    # Assert
    assert chunks == []


def test_text_shorter_than_one_chunk_is_one_chunk() -> None:
    """A short note must not be cut up for no reason."""
    # Arrange
    text = "A short note."

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert chunks == [text]


def test_paragraphs_are_packed_until_the_chunk_is_full() -> None:
    """Whole paragraphs read better as an excerpt than fragments of one."""
    # Arrange
    # 300 + 300 fit in 800, a third 300 does not.
    first, second, third = _words(300), _words(300), _words(300)
    text = PARAGRAPH_BREAK.join([first, second, third])

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert chunks[0] == first + PARAGRAPH_BREAK + second
    assert chunks[1].endswith(third)
    assert len(chunks) == 2


def test_no_chunk_is_longer_than_the_limit() -> None:
    """Over-long chunks would fail the embedding model's input limit."""
    # Arrange
    text = PARAGRAPH_BREAK.join(_words(90) for _ in range(60))
    encoding = tiktoken.get_encoding(document_reader.TOKEN_ENCODING)

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert len(chunks) > 1
    assert all(len(encoding.encode(chunk)) <= CHUNK_TOKENS for chunk in chunks)


def test_a_chunk_that_exactly_fills_the_limit_is_not_split() -> None:
    """The limit is inclusive: 400 + 400 tokens is one chunk, not two."""
    # Arrange
    text = PARAGRAPH_BREAK.join([_words(400), _words(400)])

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert chunks == [text]


def test_each_chunk_starts_with_the_tail_of_the_one_before() -> None:
    """A sentence cut at a boundary must be whole in one of the two chunks."""
    # Arrange
    # 17 paragraphs of 50 tokens; 16 fill a chunk, the overlap is the last two.
    paragraphs = [f"{index} {_words(48)}" for index in range(17)]
    text = PARAGRAPH_BREAK.join(paragraphs)

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert chunks[1].startswith(PARAGRAPH_BREAK.join(paragraphs[14:16]))
    assert chunks[1].endswith(paragraphs[16])


def test_a_paragraph_longer_than_a_chunk_is_split_at_words() -> None:
    """One huge paragraph (a PDF page with no blank lines) must still be chunked."""
    # Arrange
    text = _words(3000)

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert len(chunks) > 1
    assert all(set(chunk.split()) == {"word"} for chunk in chunks)


def test_polish_text_is_never_cut_inside_a_character() -> None:
    """A mid-character cut would turn Polish letters into replacement marks."""
    # Arrange
    text = " ".join(["zażółć gęślą jaźń"] * 1500)

    # Act
    chunks = split_into_chunks(text)

    # Assert
    assert len(chunks) > 1
    assert all("�" not in chunk for chunk in chunks)
    assert all(set(chunk.split()) <= {"zażółć", "gęślą", "jaźń"} for chunk in chunks)


def test_a_single_word_longer_than_a_chunk_is_kept_whole() -> None:
    """The splitter cuts at word boundaries only; it never invents a cut inside a word."""
    # Arrange
    word = LONG_WORD

    # Act
    chunks = split_into_chunks(word)

    # Assert
    assert chunks == [LONG_WORD]


# --- read_document ---


@pytest.mark.anyio
async def test_a_text_file_is_decoded() -> None:
    """Plain text uploads are the simplest supported type."""
    # Arrange
    body = "Zażółć gęślą jaźń".encode()

    # Act
    text = await read_document(body, "notes.txt")

    # Assert
    assert text == "Zażółć gęślą jaźń"


@pytest.mark.anyio
async def test_a_pdf_gives_its_text() -> None:
    """The PDF's page text is what gets chunked and searched."""
    # Arrange
    body = _text_pdf(pages=1, text="Hello PDF")

    # Act
    text = await read_document(body, "report.pdf")

    # Assert
    assert "Hello PDF" in text


@pytest.mark.anyio
async def test_a_file_of_exactly_the_byte_cap_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is inclusive: a file of exactly the limit is allowed."""
    # Arrange
    body = b"twelve bytes"
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_BYTES", len(body))

    # Act
    text = await read_document(body, "a.txt")

    # Assert
    assert text == "twelve bytes"


@pytest.mark.anyio
async def test_a_file_one_byte_over_the_byte_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A big file would hold a worker and a large embedding bill."""
    # Arrange
    body = b"twelve bytes"
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_BYTES", len(body) - 1)

    # Act + Assert
    with pytest.raises(DocumentTooLargeError):
        await read_document(body, "a.txt")


@pytest.mark.anyio
async def test_a_pdf_at_the_page_cap_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The page cap is inclusive."""
    # Arrange
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_PAGES", PAGE_CAP)
    body = _text_pdf(pages=PAGE_CAP)

    # Act
    text = await read_document(body, "a.pdf")

    # Assert
    assert text.count("Hello PDF") == PAGE_CAP


@pytest.mark.anyio
async def test_a_pdf_one_page_over_the_page_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Page text extraction is CPU-bound; a huge PDF would stall the worker."""
    # Arrange
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_PAGES", PAGE_CAP)
    body = _text_pdf(pages=PAGE_CAP + 1)

    # Act + Assert
    with pytest.raises(DocumentTooLargeError):
        await read_document(body, "a.pdf")


@pytest.mark.anyio
async def test_a_scanned_pdf_with_no_text_is_unreadable() -> None:
    """Without OCR a page image has nothing to search; say so instead of storing nothing."""
    # Arrange
    body = _blank_pdf()

    # Act + Assert
    with pytest.raises(DocumentUnreadableError):
        await read_document(body, "scan.pdf")


@pytest.mark.anyio
async def test_a_corrupt_pdf_is_unreadable() -> None:
    """pypdf raises many types on bad input; the user must see one clear error."""
    # Arrange
    body = b"not really a pdf"

    # Act + Assert
    with pytest.raises(DocumentUnreadableError):
        await read_document(body, "broken.pdf")


@pytest.mark.anyio
async def test_a_text_file_that_is_not_utf8_is_unreadable() -> None:
    """Guessing an encoding would store garbled text silently."""
    # Arrange
    body = "zażółć".encode("iso8859-2")

    # Act + Assert
    with pytest.raises(DocumentUnreadableError):
        await read_document(body, "old.txt")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "filename", ["letter.docx", "README"], ids=[".docx", "no extension"]
)
async def test_an_unsupported_file_type_is_unreadable(filename: str) -> None:
    """Only PDF and .txt are read; anything else is refused with the supported types."""
    # Arrange
    body = b"text"

    # Act + Assert
    with pytest.raises(DocumentUnreadableError):
        await read_document(body, filename)


@pytest.mark.anyio
async def test_the_type_is_read_from_the_file_name_in_any_case() -> None:
    """Phones and Windows often upload NOTES.TXT; refusing it would surprise people."""
    # Arrange
    body = b"upper"

    # Act
    text = await read_document(body, "NOTES.TXT")

    # Assert
    assert text == "upper"


@pytest.mark.anyio
async def test_an_empty_file_is_unreadable() -> None:
    """An empty file has no chunks and would leave a thread with a document that answers nothing."""
    # Arrange
    body = b"  \n "

    # Act + Assert
    with pytest.raises(DocumentUnreadableError):
        await read_document(body, "empty.txt")


@pytest.mark.anyio
async def test_a_text_file_with_a_nul_byte_is_unreadable() -> None:
    """Postgres text columns cannot hold NUL; found after embedding it is a 500 and a wasted bill."""
    # Arrange
    body = b"before\x00after"

    # Act + Assert
    with pytest.raises(DocumentUnreadableError):
        await read_document(body, "a.txt")


@pytest.mark.anyio
async def test_a_pdf_whose_text_has_a_nul_byte_is_unreadable() -> None:
    """A PDF can extract NUL too, and it must be refused the same way as a text file."""
    # Arrange
    body = _text_pdf(pages=1)

    # Act + Assert
    with (
        patch.object(
            PdfReader, "pages", [SimpleNamespace(extract_text=lambda: "a\x00b")]
        ),
        pytest.raises(DocumentUnreadableError),
    ):
        await read_document(body, "a.pdf")


@pytest.mark.anyio
async def test_text_one_character_over_the_character_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-paragraph 25 MB file would tie up the server in the chunker before any cap fires."""
    # Arrange
    body = b"twelve bytes"
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_CHARS", len(body) - 1)

    # Act + Assert
    with pytest.raises(DocumentTooLargeError):
        await read_document(body, "a.txt")


@pytest.mark.anyio
async def test_text_of_exactly_the_character_cap_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is inclusive: text of exactly the limit is allowed."""
    # Arrange
    body = b"twelve bytes"
    monkeypatch.setattr(document_reader, "MAX_DOCUMENT_CHARS", len(body))

    # Act
    text = await read_document(body, "a.txt")

    # Assert
    assert text == "twelve bytes"


def test_the_character_cap_is_four_characters_for_each_token_of_the_chunk_budget() -> (
    None
):
    """The cap must stay in step with the chunk cap and chunk size, or it refuses valid files."""
    # Arrange
    expected = 1_500 * 800 * 4

    # Act
    cap = document_reader.MAX_DOCUMENT_CHARS

    # Assert
    assert cap == expected
