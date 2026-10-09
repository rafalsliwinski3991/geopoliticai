"""Gemini's reading of one public YouTube video (brainstorm 2026Sep30 Q17c).

The Gemini API processes the video itself, frames and audio, not captions:
YouTube refuses caption requests from the production server (VPS probe,
2026-09-30). Gemini's OpenAI-compatible endpoint takes no video, so this is
the forecaster's only call through the native `google-genai` SDK.

F2 makes a refused, rate-limited, failed or timed-out call a soft stop, so
exactly those become `VideoUnavailableError`, which `tools.ask_video` turns
into a message: the API's own error responses (`errors.APIError`, 4xx and
5xx) and transport failures and timeouts (`httpx.HTTPError`; the SDK uses
httpx, as aiohttp is not installed). Anything else is a bug and propagates
as a hard error (guidance review).
"""

from __future__ import annotations

import logging
import os

import httpx
from google import genai
from google.genai import errors, types

from agents.deep_forecaster.config import VIDEO_SETTINGS
from agents.deep_forecaster.prompts import VIDEO_NOT_DISCUSSED, VIDEO_PROMPT

logger = logging.getLogger(__name__)


class VideoUnavailableError(Exception):
    """Gemini refused, rate-limited, failed or timed out on one video (F2)."""


async def watch_video(url: str, question: str) -> str:
    """Return Gemini's notes on what the public video at `url` says about `question`.

    Raises `VideoUnavailableError` for a provider or transport failure, and
    for a missing `GEMINI_API_KEY`, so the scout sees the documented soft
    stop instead of a hard `KeyError` (review thread, #140).
    """
    try:
        api_key = os.environ["GEMINI_API_KEY"]
    except KeyError as exc:
        raise VideoUnavailableError("GEMINI_API_KEY is not set") from exc
    try:
        async with genai.Client(api_key=api_key).aio as client:
            response = await client.models.generate_content(
                model=VIDEO_SETTINGS.model,
                contents=types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            file_data=types.FileData(file_uri=url),
                            # A custom `fps` is documented for static processing
                            # only; static is the committed mode. The probe
                            # measured static at 12 s and ~130k prompt tokens
                            # for a ~1-hour video (fps respected). Sending
                            # `media_processing` for a YouTube URL is a 400
                            # ("mime_type must be set when media_processing is
                            # specified", unit 03 probe 2026-10-01), so no
                            # processing field is sent at all.
                            video_metadata=types.VideoMetadata(fps=VIDEO_SETTINGS.fps),
                        ),
                        types.Part(
                            text=VIDEO_PROMPT.format(
                                question=question, not_discussed=VIDEO_NOT_DISCUSSED
                            )
                        ),
                    ],
                ),
                config=types.GenerateContentConfig(
                    media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
                    max_output_tokens=VIDEO_SETTINGS.max_output_tokens,
                    # Dynamic thinking could spend the whole output cap and
                    # return empty text (framework review).
                    thinking_config=types.ThinkingConfig(
                        thinking_level=types.ThinkingLevel.LOW
                    ),
                    http_options=types.HttpOptions(
                        timeout=int(VIDEO_SETTINGS.timeout_seconds * 1000)
                    ),
                ),
            )
    except (errors.APIError, httpx.HTTPError) as exc:
        raise VideoUnavailableError(type(exc).__name__) from exc
    usage = response.usage_metadata
    # The smoke run's measurement (F3): prompt tokens near 100 per second of
    # video mean `fps` was ignored for a YouTube URL.
    logger.info(
        "ask_video: %s prompt tokens",
        usage.prompt_token_count if usage is not None else "unknown",
    )
    return (response.text or "").strip()
