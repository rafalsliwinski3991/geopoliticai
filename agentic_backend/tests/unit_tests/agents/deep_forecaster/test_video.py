"""Unit tests for `agents.deep_forecaster.video`'s notes cache."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from google.genai import errors, types
from langgraph.store.memory import InMemoryStore

import agents.deep_forecaster.video as video_module
from agents.deep_forecaster.config import VIDEO_SETTINGS
from agents.deep_forecaster.video import (
    NOTES_NAMESPACE,
    VideoUnavailableError,
    _notes_key,
    watch_video,
)


class _GeminiRecorder:
    """Records watch_video's Gemini calls; returns scripted notes."""

    def __init__(self, notes: str = "Points from the video.") -> None:
        self.notes = notes
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, url: str, question: str) -> str:
        self.calls.append((url, question))
        return self.notes


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _GeminiRecorder:
    gemini = _GeminiRecorder()
    monkeypatch.setattr(video_module, "_ask_gemini", gemini)
    return gemini


@pytest.mark.anyio
async def test_a_cached_question_never_reaches_gemini(
    recorder: _GeminiRecorder,
) -> None:
    # Arrange
    store = InMemoryStore()
    # Act
    first = await watch_video(
        "https://www.youtube.com/watch?v=abc", "Russia and NATO", store
    )
    second = await watch_video(
        "https://www.youtube.com/watch?v=abc", "  russia AND nato ", store
    )
    # Assert
    assert first == second == "Points from the video."
    assert len(recorder.calls) == 1
    items = await store.asearch(NOTES_NAMESPACE)
    assert len(items) == 1
    assert items[0].value["question"] == "Russia and NATO"


@pytest.mark.anyio
async def test_another_question_or_video_is_a_miss(
    recorder: _GeminiRecorder,
) -> None:
    # Arrange
    store = InMemoryStore()
    # Act
    await watch_video("https://www.youtube.com/watch?v=abc", "Russia and NATO", store)
    await watch_video("https://www.youtube.com/watch?v=abc", "Poland and NATO", store)
    await watch_video("https://www.youtube.com/watch?v=xyz", "Russia and NATO", store)
    # Assert
    assert len(recorder.calls) == 3


@pytest.mark.anyio
async def test_empty_notes_are_not_cached(recorder: _GeminiRecorder) -> None:
    # Arrange
    recorder.notes = ""
    store = InMemoryStore()
    # Act
    notes = await watch_video("https://www.youtube.com/watch?v=abc", "q", store)
    # Assert
    assert notes == ""
    items = await store.asearch(NOTES_NAMESPACE)
    assert items == []


@pytest.mark.anyio
async def test_not_discussed_is_cached(recorder: _GeminiRecorder) -> None:
    from agents.deep_forecaster.prompts import VIDEO_NOT_DISCUSSED

    # Arrange
    recorder.notes = VIDEO_NOT_DISCUSSED
    store = InMemoryStore()
    # Act
    first = await watch_video("https://www.youtube.com/watch?v=abc", "q", store)
    second = await watch_video("https://www.youtube.com/watch?v=abc", "q", store)
    # Assert
    assert first == second == VIDEO_NOT_DISCUSSED
    assert len(recorder.calls) == 1


@pytest.mark.anyio
async def test_without_a_store_gemini_is_always_called(
    recorder: _GeminiRecorder,
) -> None:
    # Arrange: no store at all, so every question must miss the cache.
    # Act
    await watch_video("https://www.youtube.com/watch?v=abc", "q")
    await watch_video("https://www.youtube.com/watch?v=abc", "q")
    # Assert
    assert len(recorder.calls) == 2


@pytest.mark.anyio
async def test_a_database_failure_is_a_miss(recorder: _GeminiRecorder) -> None:
    import psycopg

    # Arrange
    class _DeadStore:
        async def aget(self, namespace: Any, key: str) -> Any:
            raise psycopg.OperationalError("pool gone")

        async def aput(self, namespace: Any, key: str, value: Any) -> None:
            raise psycopg.OperationalError("pool gone")

    store: Any = _DeadStore()
    # Act
    notes = await watch_video("https://www.youtube.com/watch?v=abc", "q", store)
    # Assert: the forecast still gets its notes.
    assert notes == "Points from the video."
    assert len(recorder.calls) == 1


@pytest.mark.anyio
async def test_a_write_failure_still_returns_notes(
    recorder: _GeminiRecorder, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    import psycopg

    # Arrange
    class _ReadOnlyStore:
        async def aget(self, namespace: Any, key: str) -> Any:
            return None

        async def aput(self, namespace: Any, key: str, value: Any) -> None:
            raise psycopg.OperationalError("read-only")

    caplog.set_level(logging.WARNING, logger=video_module.__name__)
    # Act
    notes = await watch_video(
        "https://www.youtube.com/watch?v=abc", "q", cast(Any, _ReadOnlyStore())
    )
    # Assert
    assert notes == "Points from the video."
    assert "notes not cached" in caplog.text


@pytest.mark.anyio
async def test_a_non_psycopg_error_propagates(
    recorder: _GeminiRecorder,
) -> None:
    # Arrange
    class _BrokenStore:
        async def aget(self, namespace: Any, key: str) -> Any:
            raise RuntimeError("bug")

    # Act + Assert
    with pytest.raises(RuntimeError, match="bug"):
        await watch_video(
            "https://www.youtube.com/watch?v=abc", "q", cast(Any, _BrokenStore())
        )


@pytest.mark.anyio
async def test_a_nul_is_stripped_before_caching(
    recorder: _GeminiRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    recorder.notes = "bad\x00note"
    stored: dict[str, Any] = {}

    class _SpyStore:
        async def aget(self, namespace: Any, key: str) -> Any:
            return None

        async def aput(self, namespace: Any, key: str, value: Any) -> None:
            stored["value"] = value

    # Act
    notes = await watch_video(
        "https://www.youtube.com/watch?v=abc", "q", cast(Any, _SpyStore())
    )
    # Assert
    assert notes == "bad\x00note"
    assert stored["value"]["notes"] == "badnote"


def test_the_notes_key_normalises_the_question() -> None:
    # Arrange (nothing to set up: the key's normalisation is the whole test)
    # Act + Assert
    assert _notes_key(
        "https://www.youtube.com/watch?v=abc", "  Russia   and NATO "
    ) == _notes_key("https://www.youtube.com/watch?v=abc", "russia and nato")
    assert _notes_key("https://www.youtube.com/watch?v=abc", "q") != _notes_key(
        "https://www.youtube.com/watch?v=xyz", "q"
    )


# --- `_ask_gemini` itself (restored per review thread, #151) -----------------


class _FakeModels:
    """Records `generate_content` kwargs; returns or raises as configured."""

    def __init__(
        self, text: str = "  notes  ", fail: BaseException | None = None
    ) -> None:
        self.recorded: dict[str, Any] | None = None
        self.text = text
        self.fail = fail

    async def generate_content(self, **kwargs: Any) -> Any:
        if self.fail is not None:
            raise self.fail
        self.recorded = kwargs
        return SimpleNamespace(
            text=self.text, usage_metadata=SimpleNamespace(prompt_token_count=117)
        )


class _FakeClient:
    """The patched `genai.Client`: an async-context-manager `.aio`."""

    def __init__(self, models: _FakeModels, **kwargs: Any) -> None:
        self.models = models
        self.kwargs = kwargs

    @property
    def aio(self) -> Any:
        class _Aio:
            def __init__(self, client: _FakeClient) -> None:
                self.client = client

            async def __aenter__(self) -> _FakeClient:
                return self.client

            async def __aexit__(self, *exc: object) -> None:
                return None

        return _Aio(self)


def _patch_gemini(monkeypatch: pytest.MonkeyPatch, models: _FakeModels) -> None:
    from google import genai as google_genai

    monkeypatch.setattr(
        google_genai, "Client", lambda **kwargs: _FakeClient(models, **kwargs)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


@pytest.mark.anyio
async def test_ask_gemini_sends_the_url_at_low_fps_without_media_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    models = _FakeModels()
    _patch_gemini(monkeypatch, models)
    # Act
    notes = await video_module._ask_gemini(
        "https://www.youtube.com/watch?v=abcdefghijk", "Russia and NATO"
    )
    # Assert
    assert notes == "notes"
    recorded = models.recorded
    assert recorded is not None
    parts = recorded["contents"].parts
    assert parts[0].file_data.file_uri == "https://www.youtube.com/watch?v=abcdefghijk"
    # `media_processing` for a YouTube URL is a 400: nothing is sent at all.
    assert all(part.media_processing is None for part in parts)
    assert parts[0].video_metadata.fps == VIDEO_SETTINGS.fps
    config = recorded["config"]
    assert config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert config.max_output_tokens == VIDEO_SETTINGS.max_output_tokens
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert config.http_options.timeout == 120_000
    assert "Russia and NATO" in parts[1].text
    assert recorded["model"] == VIDEO_SETTINGS.model


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fail",
    [
        errors.ClientError(429, {"error": {"message": "quota"}}),
        errors.ServerError(503, {"error": {"message": "busy"}}),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_provider_and_transport_failures_are_video_unavailable(
    fail: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    models = _FakeModels(fail=fail)
    _patch_gemini(monkeypatch, models)
    # Act + Assert
    with pytest.raises(VideoUnavailableError):
        await video_module._ask_gemini(
            "https://www.youtube.com/watch?v=abcdefghijk", "q"
        )


@pytest.mark.anyio
async def test_a_programming_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    models = _FakeModels(fail=TypeError("bug"))
    _patch_gemini(monkeypatch, models)
    # Act + Assert
    with pytest.raises(TypeError):
        await video_module._ask_gemini(
            "https://www.youtube.com/watch?v=abcdefghijk", "q"
        )


@pytest.mark.anyio
async def test_an_empty_and_a_stripped_reply_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    models = _FakeModels(text="")
    _patch_gemini(monkeypatch, models)
    # Act + Assert
    assert (
        await video_module._ask_gemini(
            "https://www.youtube.com/watch?v=abcdefghijk", "q"
        )
        == ""
    )
    models_stripped = _FakeModels(text="  notes  ")
    _patch_gemini(monkeypatch, models_stripped)
    # Act + Assert
    assert (
        await video_module._ask_gemini(
            "https://www.youtube.com/watch?v=abcdefghijk", "q"
        )
        == "notes"
    )
