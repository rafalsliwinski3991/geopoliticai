import pytest
from langchain_openai import OpenAIEmbeddings

from services import embeddings
from services.embeddings import embed_query, embed_texts
from shared.errors import LLMInvocationError

FIRST_VECTOR = [0.1, 0.2]
SECOND_VECTOR = [0.3, 0.4]


class ScriptedEmbeddings:
    """Returns the scripted vectors and records each text batch it was given."""

    def __init__(
        self, vectors: list[list[float]] | None = None, error: Exception | None = None
    ) -> None:
        self.vectors = vectors or []
        self.error = error
        self.calls: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.error:
            raise self.error
        return self.vectors

    async def aembed_query(self, text: str) -> list[float]:
        self.calls.append([text])
        if self.error:
            raise self.error
        return self.vectors[0]


def _use(monkeypatch: pytest.MonkeyPatch, fake: ScriptedEmbeddings) -> None:
    monkeypatch.setattr(embeddings, "_build_embeddings", lambda: fake)


@pytest.mark.anyio
async def test_texts_come_back_as_vectors_in_the_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller zips vectors to chunks by position, so order is the contract."""
    # Arrange
    fake = ScriptedEmbeddings([FIRST_VECTOR, SECOND_VECTOR])
    _use(monkeypatch, fake)

    # Act
    result = await embed_texts(["one", "two"])

    # Assert
    assert result == [FIRST_VECTOR, SECOND_VECTOR]
    assert fake.calls == [["one", "two"]]


@pytest.mark.anyio
async def test_no_texts_make_no_provider_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty batch would be a paid, pointless request."""
    # Arrange
    fake = ScriptedEmbeddings()
    _use(monkeypatch, fake)

    # Act
    result = await embed_texts([])

    # Assert
    assert result == []
    assert fake.calls == []


@pytest.mark.anyio
async def test_a_provider_failure_is_an_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API reports a provider outage as a 502, never a raw client exception."""
    # Arrange
    _use(monkeypatch, ScriptedEmbeddings(error=RuntimeError("boom")))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await embed_texts(["one"])


@pytest.mark.anyio
async def test_a_short_provider_reply_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing vector would shift every later chunk onto the wrong embedding."""
    # Arrange
    _use(monkeypatch, ScriptedEmbeddings([FIRST_VECTOR]))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await embed_texts(["one", "two"])


@pytest.mark.anyio
async def test_a_query_is_one_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search compares one query vector to the stored chunk vectors."""
    # Arrange
    fake = ScriptedEmbeddings([FIRST_VECTOR])
    _use(monkeypatch, fake)

    # Act
    result = await embed_query("what is the deadline?")

    # Assert
    assert result == FIRST_VECTOR
    assert fake.calls == [["what is the deadline?"]]


@pytest.mark.anyio
async def test_a_query_provider_failure_is_an_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed query embedding must be a 502, not a search with no vector."""
    # Arrange
    _use(monkeypatch, ScriptedEmbeddings(error=RuntimeError("boom")))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await embed_query("question")


def test_the_client_does_not_retokenise_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chunks are already token-sized; the client's own pass would block the event loop."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    # Act
    client = embeddings._build_embeddings()

    # Assert
    assert isinstance(client, OpenAIEmbeddings)
    assert client.check_embedding_ctx_length is False
