"""Unit tests for `agents.deep_forecaster.video`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors, types

import agents.deep_forecaster.video as video_module
from agents.deep_forecaster.config import VIDEO_SETTINGS, VideoSettings
from agents.deep_forecaster.video import (
    VideoUnavailableError,
    watch_video,
)


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
        return SimpleNamespace(text=self.text, usage_metadata=None)


class _FakeAio:
    """The async context manager `.aio` returns."""

    def __init__(self, client: _FakeClient) -> None:
        self.client = client

    async def __aenter__(self) -> _FakeClient:
        return self.client

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeClient:
    """The patched `genai.Client`: an async-context-manager `.aio`."""

    def __init__(self, models: _FakeModels, **kwargs: Any) -> None:
        self.models = models
        self.kwargs = kwargs

    @property
    def aio(self) -> _FakeAio:
        return _FakeAio(self)


def _patch(monkeypatch: pytest.MonkeyPatch, models: _FakeModels) -> None:
    from google import genai as google_genai

    monkeypatch.setattr(
        google_genai, "Client", lambda **kwargs: _FakeClient(models, **kwargs)
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


@pytest.mark.anyio
async def test_watch_video_sends_the_url_at_low_fps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _FakeModels()
    _patch(monkeypatch, models)
    monkeypatch.setattr(
        video_module, "VIDEO_SETTINGS", VideoSettings(processing="static")
    )
    # Act
    notes = await watch_video("https://www.youtube.com/watch?v=abc", "Russia and NATO")
    # Assert
    assert notes == "notes"
    recorded = models.recorded
    assert recorded is not None
    parts = recorded["contents"].parts
    assert parts[0].file_data.file_uri == "https://www.youtube.com/watch?v=abc"
    assert parts[0].media_processing == types.MediaProcessing.STATIC
    assert parts[0].video_metadata.fps == 0.1
    assert parts[0].video_metadata.fps == VIDEO_SETTINGS.fps
    config = recorded["config"]
    assert config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert config.http_options.timeout == 120_000
    assert "Russia and NATO" in parts[1].text
    assert recorded["model"] == VIDEO_SETTINGS.model


@pytest.mark.anyio
async def test_agentic_processing_sends_no_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    models = _FakeModels()
    _patch(monkeypatch, models)
    monkeypatch.setattr(
        video_module, "VIDEO_SETTINGS", VideoSettings(processing="agentic")
    )
    await watch_video("https://www.youtube.com/watch?v=abc", "q")
    recorded = models.recorded
    assert recorded is not None
    parts = recorded["contents"].parts
    assert parts[0].media_processing == types.MediaProcessing.AGENTIC
    assert parts[0].video_metadata is None


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
    models = _FakeModels(fail=fail)
    _patch(monkeypatch, models)
    with pytest.raises(VideoUnavailableError):
        await watch_video("https://www.youtube.com/watch?v=abc", "q")


@pytest.mark.anyio
async def test_a_programming_error_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _FakeModels(fail=TypeError("bug"))
    _patch(monkeypatch, models)
    with pytest.raises(TypeError):
        await watch_video("https://www.youtube.com/watch?v=abc", "q")


@pytest.mark.anyio
async def test_empty_and_off_topic_replies_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = _FakeModels(text="")
    _patch(monkeypatch, models)
    assert await watch_video("https://www.youtube.com/watch?v=abc", "q") == ""
