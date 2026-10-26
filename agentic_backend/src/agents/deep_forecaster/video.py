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

import asyncio
import hashlib
import logging
import os

import httpx
import psycopg
from google import genai
from google.genai import errors, types
from langgraph.store.base import BaseStore

from agents.deep_forecaster.config import VIDEO_SETTINGS
from agents.deep_forecaster.prompts import VIDEO_NOT_DISCUSSED, VIDEO_PROMPT

logger = logging.getLogger(__name__)

# Gemini's notes, cached by video and question (user decision 2026-10-01).
# Items expire with the API store's TTL (`api.STORE_TTL`, 30 days).
NOTES_NAMESPACE = ("forecast_video_notes",)

# Per-key request coalescing (review thread, #151): `aget` then call then
# `aput` is not atomic across requests, so two forecasts asking the same
# video and question at once would both miss and both pay Gemini. The
# second caller waits, then re-checks the cache and either finds the first
# caller's notes or becomes the owner that calls Gemini.
_CACHE_LOCKS: dict[str, asyncio.Lock] = {}


class VideoUnavailableError(Exception):
    """Gemini refused, rate-limited, failed or timed out on one video (F2)."""


def _cache_lock(key: str) -> asyncio.Lock:
    """Return the coalescing lock for one cache key."""
    return _CACHE_LOCKS.setdefault(key, asyncio.Lock())


def _notes_key(url: str, question: str) -> str:
    """Return the cache key for one canonical video URL and one question.

    The question is compared without case or extra whitespace; the scouts
    write it, so the same wording is what makes a hit.
    """
    normalised = " ".join(question.split()).casefold()
    return hashlib.sha256(f"{url}\n{normalised}".encode()).hexdigest()


async def _cached_notes(store: BaseStore, key: str) -> str | None:
    """Return the cached notes for `key`, or None (a database error never fails)."""
    try:
        item = await store.aget(NOTES_NAMESPACE, key)
    except psycopg.Error:
        logger.warning("ask_video: notes cache unreadable", exc_info=True)
        return None
    if item is not None:
        logger.info("ask_video: cached notes")
        return str(item.value["notes"])
    return None


async def _store_notes(
    store: BaseStore, key: str, url: str, question: str, notes: str
) -> None:
    """Write `notes` into the cache; a database error never fails a forecast."""
    try:
        await store.aput(
            NOTES_NAMESPACE,
            key,
            # jsonb refuses NUL, which a model's text can carry.
            {"url": url, "question": question, "notes": notes.replace("\x00", "")},
        )
    except psycopg.Error:
        logger.warning("ask_video: notes not cached", exc_info=True)


async def watch_video(url: str, question: str, store: BaseStore | None = None) -> str:
    """Return Gemini's notes on what the public video at `url` says about `question`.

    With a store, notes cached for the same video and question are returned
    without calling Gemini, and new non-empty notes are cached. Concurrent
    callers of the same video and question coalesce: the first inside the
    key's lock calls Gemini, the second re-checks and finds the notes
    (review thread, #151). A database failure on either side is logged and
    skipped: the cache only saves Gemini time, and an error there must not
    fail a forecast that has already been charged and already has its notes
    (framework review). Raises `VideoUnavailableError` for a provider or
    transport failure, and for a missing `GEMINI_API_KEY`, so the scout
    sees the documented soft stop instead of a hard `KeyError` (thread #140).
    """
    key = _notes_key(url, question)
    if store is None:
        return await _ask_gemini(url, question)
    hit = await _cached_notes(store, key)
    if hit is not None:
        return hit
    async with _cache_lock(key):
        # Re-check under the lock: the pre-check outside raced a caller that
        # had already taken the key and was inside Gemini.
        hit = await _cached_notes(store, key)
        if hit is not None:
            return hit
        notes = await _ask_gemini(url, question)
        if notes:
            await _store_notes(store, key, url, question, notes)
        return notes


async def _ask_gemini(url: str, question: str) -> str:
    """Call Gemini once on the video; raises `VideoUnavailableError` on provider failure."""
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
