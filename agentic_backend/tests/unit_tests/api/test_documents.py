import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from api import documents, rate_limit
from api.app import answer_pipeline_error, app
from shared.config import MAX_DOCUMENTS_PER_USER
from shared.errors import DocumentLimitError, LLMInvocationError

THREAD_URL = "/api/threads/t-1/document"
UPLOAD_URL = f"{THREAD_URL}?filename=report.txt"
TEXT_FILE = b"The ceasefire talks resumed in Geneva on Monday."
USER_ID = 1
OTHER_USER_ID = 2
VECTOR = [0.25, -0.5]


@dataclass
class FakeChunkStore:
    """Stands in for the chunk SQL and the embeddings call, and records every call.

    A call the test did not expect shows up in a list that should be empty.
    """

    live_documents: int = 0
    document_name: str | None = None
    thread_is_owned: bool = True
    thread_is_claimed: bool = True
    embed_error: BaseException | None = None
    search_rows: list[dict[str, Any]] = field(default_factory=list)
    embedded: list[list[str]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    replacements: list[dict[str, Any]] = field(default_factory=list)
    deletions: list[dict[str, Any]] = field(default_factory=list)
    searches: list[dict[str, Any]] = field(default_factory=list)

    async def count_live_documents(self, pool: Any, **kwargs: Any) -> int:
        return self.live_documents

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.embedded.append(texts)
        if self.embed_error is not None:
            raise self.embed_error
        return [VECTOR for _ in texts]

    async def claim_thread(self, pool: Any, **kwargs: Any) -> bool:
        self.claims.append(kwargs)
        return self.thread_is_claimed

    async def replace_chunks(self, pool: Any, **kwargs: Any) -> None:
        self.replacements.append(kwargs)

    async def owns_thread(self, pool: Any, **kwargs: Any) -> bool:
        return self.thread_is_owned

    async def delete_chunks(self, pool: Any, **kwargs: Any) -> int:
        self.deletions.append(kwargs)
        return 3

    async def read_document_name(self, pool: Any, **kwargs: Any) -> str | None:
        return self.document_name

    async def search_chunks(self, pool: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.searches.append(kwargs)
        return self.search_rows


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> FakeChunkStore:
    """Every chunk query and embedding call goes to one recording fake."""
    fake = FakeChunkStore()
    for name in (
        "count_live_documents",
        "embed_texts",
        "claim_thread",
        "replace_chunks",
        "owns_thread",
        "delete_chunks",
        "read_document_name",
        "search_chunks",
    ):
        monkeypatch.setattr(documents, name, getattr(fake, name))
    return fake


@pytest.mark.anyio
async def test_an_upload_stores_the_file_and_reports_its_chunk_count(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """The chat page shows the file name and trusts the count the route reports."""
    # Arrange
    expected_body = {"filename": "report.txt", "chunks": 1}

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 200
    assert response.json() == expected_body
    assert store.replacements == [
        {
            "thread_id": "t-1",
            "user_id": USER_ID,
            "filename": "report.txt",
            "texts": [TEXT_FILE.decode()],
            "embeddings": [VECTOR],
        }
    ]


@pytest.mark.anyio
async def test_an_upload_creates_the_thread_when_it_is_new(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """A user may attach a file before the first question, so the upload claims the thread."""
    # Arrange
    expected_claim = {"thread_id": "t-1", "user_id": USER_ID, "title": "report.txt"}

    # Act
    await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert store.claims == [expected_claim]


@pytest.mark.anyio
async def test_an_upload_into_another_users_thread_is_refused_and_stores_nothing(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """Thread ids are chosen by the client; writing under someone else's id would
    overwrite their document."""
    # Arrange
    store.thread_is_claimed = False

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 403
    assert store.replacements == []


@pytest.mark.anyio
async def test_a_refused_foreign_thread_is_recorded_on_the_ingest_span(
    client: httpx.AsyncClient,
    store: FakeChunkStore,
    captured_spans: InMemorySpanExporter,
) -> None:
    """Every ingest branch names its outcome, so a trace explains a 403 too."""
    # Arrange
    store.thread_is_claimed = False

    # Act
    await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    (span,) = [
        s for s in captured_spans.get_finished_spans() if s.name == "document_ingest"
    ]
    assert (span.attributes or {})["document.outcome"] == "foreign_thread"


@pytest.mark.anyio
async def test_a_second_upload_replaces_the_first(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """A thread holds one document: the second file goes through `replace_chunks`,
    which swaps the old rows for the new in one transaction."""
    # Arrange
    second_url = f"{THREAD_URL}?filename=second.txt"

    # Act
    await client.post(UPLOAD_URL, content=TEXT_FILE)
    await client.post(second_url, content=b"A second file.")

    # Assert
    assert [call["filename"] for call in store.replacements] == [
        "report.txt",
        "second.txt",
    ]


@pytest.mark.anyio
async def test_the_sixth_document_is_refused_before_any_embedding(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """Embedding costs money; a user at the cap must not spend any on an upload that
    will be refused."""
    # Arrange
    store.live_documents = MAX_DOCUMENTS_PER_USER

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 409
    assert store.embedded == []


@pytest.mark.anyio
async def test_a_file_over_the_byte_cap_is_refused(
    client: httpx.AsyncClient, store: FakeChunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap bounds the memory one upload can take."""
    # Arrange
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", len(TEXT_FILE))

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE + b"!")

    # Assert
    assert response.status_code == 413
    assert store.replacements == []


@pytest.mark.anyio
async def test_a_body_over_the_cap_is_refused_before_it_is_fully_read(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A chunked body has no declared length; the route must stop counting at the cap
    instead of buffering a body of any size."""
    # Arrange
    cap = 10
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", cap)
    parts_sent: list[bytes] = []

    async def body() -> Any:
        for _ in range(100):
            part = b"x" * cap
            parts_sent.append(part)
            yield part

    # Act
    response = await client.post(UPLOAD_URL, content=body())

    # Assert
    assert response.status_code == 413
    assert len(parts_sent) < 100


@pytest.mark.anyio
async def test_a_declared_length_over_the_cap_is_refused_before_reading(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that announces an oversized body is turned away without reading any of it."""
    # Arrange
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 5)
    parts_sent: list[bytes] = []

    async def body() -> Any:
        parts_sent.append(b"x")
        yield b"x"

    # Act
    response = await client.post(
        UPLOAD_URL, content=body(), headers={"content-length": "1000"}
    )

    # Assert
    assert response.status_code == 413
    assert parts_sent == []


@pytest.mark.anyio
async def test_a_file_with_too_many_chunks_is_refused_before_embedding(
    client: httpx.AsyncClient, store: FakeChunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chunk cap is what bounds the embedding bill of one upload."""
    # Arrange
    monkeypatch.setattr(documents, "MAX_DOCUMENT_CHUNKS", 2)
    monkeypatch.setattr(documents, "split_into_chunks", lambda text: ["a", "b", "c"])

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 413
    assert store.embedded == []


@pytest.mark.anyio
async def test_an_unsupported_file_is_refused_and_creates_no_thread(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """A refused upload must not leave an empty conversation in the sidebar."""
    # Arrange
    docx_url = f"{THREAD_URL}?filename=report.docx"

    # Act
    response = await client.post(docx_url, content=TEXT_FILE)

    # Assert
    assert response.status_code == 422
    assert response.json() == {"detail": "Upload a PDF or a .txt file."}
    assert store.claims == []


@pytest.mark.anyio
async def test_a_provider_failure_keeps_the_old_document_and_creates_no_thread(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """The embeddings are fetched before anything is written, so an outage loses
    nothing the user already had."""
    # Arrange
    store.embed_error = LLMInvocationError("provider down")

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 502
    assert (store.claims, store.replacements) == ([], [])


@pytest.mark.anyio
async def test_an_embedding_that_runs_too_long_is_a_504(
    client: httpx.AsyncClient, store: FakeChunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nginx gives up at 600 s; the route must fail first so a request the client saw
    fail cannot go on to commit its chunks."""

    # Arrange
    async def never_finishes(texts: list[str]) -> list[list[float]]:
        await asyncio.sleep(60)
        return []

    monkeypatch.setattr(documents, "EMBED_WALL_SECONDS", 0.01)
    monkeypatch.setattr(documents, "embed_texts", never_finishes)

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 504
    assert store.replacements == []


@pytest.mark.anyio
async def test_an_upload_without_a_token_is_refused_before_the_body_is_read(
    store: FakeChunkStore,
) -> None:
    """Reading a 25 MB body for a stranger is the cost the auth check exists to avoid."""
    # Arrange
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )

    # Act
    response = await anonymous.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert response.status_code == 401
    assert store.embedded == []


@pytest.mark.anyio
async def test_uploads_are_rate_limited(
    client: httpx.AsyncClient, store: FakeChunkStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embedding is not free, so uploads have a limit of their own beside the general one."""
    # Arrange
    monkeypatch.setattr(rate_limit, "UPLOAD_LIMIT_REQUESTS", 1)

    # Act
    first = await client.post(UPLOAD_URL, content=TEXT_FILE)
    second = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    assert (first.status_code, second.status_code) == (200, 429)
    assert len(store.replacements) == 1


@pytest.mark.anyio
async def test_the_ingest_span_records_bytes_chunks_and_outcome(
    client: httpx.AsyncClient, captured_spans: InMemorySpanExporter
) -> None:
    """A Phoenix trace alone must explain why an upload was kept or refused."""
    # Arrange
    expected = {
        "document.bytes": len(TEXT_FILE),
        "document.chunks": 1,
        "document.outcome": "stored",
    }

    # Act
    await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    (span,) = [
        s for s in captured_spans.get_finished_spans() if s.name == "document_ingest"
    ]
    recorded = dict(span.attributes or {})
    assert {key: recorded[key] for key in expected} == expected
    assert recorded["user.id"] == "1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C:\\Users\\me\\report.pdf", "report.pdf"),
        ("/tmp/uploads/report.pdf", "report.pdf"),
    ],
    ids=["windows path", "unix path"],
)
def test_a_path_is_cut_to_its_base_name(raw: str, expected: str) -> None:
    """The browser may send a full path; only the base name is shown and stored."""
    # Arrange
    path = raw

    # Act
    cleaned = documents.clean_filename(path)

    # Assert
    assert cleaned == expected


def test_quotes_and_brackets_are_replaced() -> None:
    """The name is placed inside a prompt wrapper, so it cannot carry quotes or angle brackets."""
    # Arrange
    raw = 'my"file<1>.txt'

    # Act
    cleaned = documents.clean_filename(raw)

    # Assert
    assert cleaned == "my_file_1_.txt"


def test_a_long_name_keeps_its_extension() -> None:
    """A cut at the length limit must not strip `.pdf`, which decides how the file is read."""
    # Arrange
    raw = "a" * 150 + ".pdf"

    # Act
    cleaned = documents.clean_filename(raw)

    # Assert
    assert cleaned == "a" * 96 + ".pdf"


def test_an_empty_name_becomes_document() -> None:
    """A name of only dots and spaces would be stored as an empty string."""
    # Arrange
    raw = " .. "

    # Act
    cleaned = documents.clean_filename(raw)

    # Assert
    assert cleaned == "document"


@pytest.mark.anyio
async def test_removing_a_document_deletes_its_chunks(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """Removing the file is how a user returns a thread to research mode."""
    # Arrange
    expected = [{"thread_id": "t-1", "user_id": USER_ID}]

    # Act
    response = await client.delete(THREAD_URL)

    # Assert
    assert response.status_code == 204
    assert store.deletions == expected


@pytest.mark.anyio
async def test_removing_from_another_users_thread_is_refused(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """Only the owner may remove a thread's document."""
    # Arrange
    store.thread_is_owned = False

    # Act
    response = await client.delete(THREAD_URL)

    # Assert
    assert response.status_code == 403
    assert store.deletions == []


@pytest.mark.anyio
async def test_removing_when_nothing_is_attached_still_succeeds(
    client: httpx.AsyncClient, store: FakeChunkStore
) -> None:
    """A double click or a retry after a lost response must not show the user an error."""
    # Arrange
    store.document_name = None

    # Act
    response = await client.delete(THREAD_URL)

    # Assert
    assert response.status_code == 204


@pytest.mark.anyio
async def test_a_thread_without_a_document_gets_an_empty_context(
    store: FakeChunkStore,
) -> None:
    """With no document the supervisor keeps its research tools."""
    # Arrange
    store.document_name = None

    # Act
    context = await documents.build_orchestrator_context(
        cast(Any, None),
        thread_id="t-1",
        user_id=USER_ID,
    )

    # Assert
    assert (context.filename, context.search_document) == (None, None)


@pytest.mark.anyio
async def test_a_thread_with_a_document_gets_a_search_that_returns_chunks(
    store: FakeChunkStore,
) -> None:
    """The agent layer never sees a row: the search maps `chunk_index` to `index` and
    queries as the thread's own user."""
    # Arrange
    store.document_name = "report.txt"
    store.search_rows = [
        {"filename": "report.txt", "chunk_index": 4, "content": "Geneva talks."}
    ]

    # Act
    context = await documents.build_orchestrator_context(
        cast(Any, None),
        thread_id="t-1",
        user_id=OTHER_USER_ID,
    )
    assert context.search_document is not None
    found = await context.search_document(VECTOR)

    # Assert
    assert context.filename == "report.txt"
    assert found == [{"filename": "report.txt", "index": 4, "text": "Geneva talks."}]
    assert store.searches[0]["user_id"] == OTHER_USER_ID
    assert store.searches[0]["embedding"] == VECTOR


def test_a_pipeline_error_raised_in_a_route_is_answered_with_its_status() -> None:
    """Only the stream turned a `PipelineError` into a frame; the upload route needs
    the same error to reach the browser as its own status and message."""
    # Arrange
    error = DocumentLimitError("You can keep 5 documents.")

    # Act
    response = asyncio.run(answer_pipeline_error(None, error))  # type: ignore[arg-type]

    # Assert
    assert response.status_code == 409
    assert json.loads(bytes(response.body)) == {"detail": "You can keep 5 documents."}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body", "status", "outcome"),
    [(b"a\x00b", 422, "unreadable"), (b"   ", 422, "unreadable")],
    ids=["a NUL byte", "no readable text"],
)
async def test_an_unreadable_file_is_recorded_on_the_ingest_span(
    client: httpx.AsyncClient,
    captured_spans: InMemorySpanExporter,
    body: bytes,
    status: int,
    outcome: str,
) -> None:
    """Every ingest branch names its outcome, so a trace explains a 422 too."""
    # Arrange: the parameters hold the file and what the trace must say.

    # Act
    response = await client.post(UPLOAD_URL, content=body)

    # Assert
    (span,) = [
        s for s in captured_spans.get_finished_spans() if s.name == "document_ingest"
    ]
    assert response.status_code == status
    assert (span.attributes or {})["document.outcome"] == outcome


@pytest.mark.anyio
async def test_text_over_the_character_cap_is_recorded_as_too_large(
    client: httpx.AsyncClient,
    captured_spans: InMemorySpanExporter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The character and page caps fire inside the reader, and the trace must still say why."""
    # Arrange
    monkeypatch.setattr(
        "services.document_reader.MAX_DOCUMENT_CHARS", len(TEXT_FILE) - 1
    )

    # Act
    response = await client.post(UPLOAD_URL, content=TEXT_FILE)

    # Assert
    (span,) = [
        s for s in captured_spans.get_finished_spans() if s.name == "document_ingest"
    ]
    assert response.status_code == 413
    assert (span.attributes or {})["document.outcome"] == "too_large"
