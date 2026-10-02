"""Unit tests for `agents.deep_forecaster.video`'s notes cache."""

from __future__ import annotations

from typing import Any, cast

import pytest
from langgraph.store.memory import InMemoryStore

from agents.deep_forecaster.video import (
    NOTES_NAMESPACE,
    _notes_key,
    watch_video,
)

video_module: Any = __import__("agents.deep_forecaster.video", fromlist=["watch_video"])


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
    store = InMemoryStore()
    # Act
    await watch_video("https://www.youtube.com/watch?v=abc", "Russia and NATO", store)
    await watch_video("https://www.youtube.com/watch?v=abc", "Poland and NATO", store)
    await watch_video("https://www.youtube.com/watch?v=xyz", "Russia and NATO", store)
    # Assert
    assert len(recorder.calls) == 3


@pytest.mark.anyio
async def test_empty_notes_are_not_cached(recorder: _GeminiRecorder) -> None:
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
    # Act
    await watch_video("https://www.youtube.com/watch?v=abc", "q")
    await watch_video("https://www.youtube.com/watch?v=abc", "q")
    # Assert
    assert len(recorder.calls) == 2


@pytest.mark.anyio
async def test_a_database_failure_is_a_miss(recorder: _GeminiRecorder) -> None:
    import psycopg

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
    class _BrokenStore:
        async def aget(self, namespace: Any, key: str) -> Any:
            raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        await watch_video(
            "https://www.youtube.com/watch?v=abc", "q", cast(Any, _BrokenStore())
        )


@pytest.mark.anyio
async def test_a_nul_is_stripped_before_caching(
    recorder: _GeminiRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    # Act + Assert
    assert _notes_key(
        "https://www.youtube.com/watch?v=abc", "  Russia   and NATO "
    ) == _notes_key("https://www.youtube.com/watch?v=abc", "russia and nato")
    assert _notes_key("https://www.youtube.com/watch?v=abc", "q") != _notes_key(
        "https://www.youtube.com/watch?v=xyz", "q"
    )
