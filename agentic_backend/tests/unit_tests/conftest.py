import io
import os
from collections.abc import Callable

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pypdf import PdfReader, PdfWriter

# OpenTelemetry allows one global tracer provider per process, so one exporter is
# shared and cleared per test.
SPAN_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="session")
def _tracer_provider() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SPAN_EXPORTER))
    trace.set_tracer_provider(provider)


@pytest.fixture(autouse=True)
def _reset_tracing_initialized() -> None:
    """`init_tracing` tests leave `_initialized` True; `start_span` would then
    call the LangChain lookup, which prints to stdout outside an instrumented run."""
    import tracing

    tracing._initialized = False


@pytest.fixture
def captured_spans(_tracer_provider: None) -> InMemorySpanExporter:
    """Spans finished during this test; `get_finished_spans()` reads them."""
    SPAN_EXPORTER.clear()
    return SPAN_EXPORTER


@pytest.fixture(scope="session", autouse=True)
def jwt_signing_key() -> None:
    """The identity tests run without a database; the key is a test constant.

    32+ bytes so PyJWT does not warn about an undersized HMAC key.
    """
    os.environ.setdefault(
        "JWT_SIGNING_KEY", "unit-test-signing-key-not-long-enough-0123456789"
    )


def _escape_pdf_string(text: str) -> str:
    """Escape text for a PDF literal string; control characters become octal escapes."""
    out = []
    for char in text:
        if char in "\\()":
            out.append("\\" + char)
        elif ord(char) < 32:
            out.append(f"\\{ord(char):03o}")
        else:
            out.append(char)
    return "".join(out)


def _build_pdf(texts: list[str], size: int = 0, padding: int = 0) -> bytes:
    """Write a minimal valid one-font PDF with one page per text.

    `size` pads the file with a comment line after the header to exactly that
    many bytes (it must exceed the unpadded size); the xref offsets count it.
    """
    if size:
        plain = len(_build_pdf(texts))
        # The startxref number gains digits with the padding: settle in two passes.
        padding = size - plain
        padding -= len(_build_pdf(texts, padding=padding)) - size
        return _build_pdf(texts, padding=padding)
    objects: list[bytes] = []
    page_ids = [4 + 2 * index for index in range(len(texts))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(texts)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, text in enumerate(texts):
        stream = f"BT /F1 12 Tf 72 700 Td ({_escape_pdf_string(text)}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[index] + 1} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    if padding:
        out += b"%" + b"x" * (padding - 2) + b"\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


@pytest.fixture
def build_pdf() -> Callable[..., bytes]:
    """Return `build_pdf(texts, size=0)`: a valid PDF with one page per text."""
    return _build_pdf


@pytest.fixture
def build_encrypted_pdf() -> Callable[..., bytes]:
    """Return `build_encrypted_pdf(texts, user_password)`: an AES-encrypted PDF.

    The owner password is always "x"; an empty `user_password` leaves the file
    openable by anyone, a real one locks it.
    """

    def build(texts: list[str], user_password: str) -> bytes:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_build_pdf(texts))))
        writer.encrypt(user_password=user_password, owner_password="x")
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    return build
