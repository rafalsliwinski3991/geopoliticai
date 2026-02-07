"""Configuration helpers and constants for the GeopoliticAI pipeline."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from dotenv import load_dotenv

ENGLISH_INFOSPHERE_SOURCES: dict[str, list[tuple[str, str]]] = {
    "left": [
        ("Jacobin", "https://jacobin.com"),
        ("Economic Policy Institute", "https://www.epi.org"),
        ("Roosevelt Institute", "https://rooseveltinstitute.org"),
    ],
    "centrist": [
        ("Brookings Institution", "https://www.brookings.edu"),
        ("Council on Foreign Relations", "https://www.cfr.org"),
        ("The Economist", "https://www.economist.com"),
    ],
    "right": [
        ("American Enterprise Institute", "https://www.aei.org"),
        ("Heritage Foundation", "https://www.heritage.org"),
        ("Hoover Institution", "https://www.hoover.org"),
    ],
    "fact": [
        ("Reuters Fact Check", "https://www.reuters.com/fact-check"),
        ("AP Fact Check", "https://apnews.com/hub/ap-fact-check"),
        ("FactCheck.org", "https://www.factcheck.org"),
    ],
    "people": [
        ("Reddit", "https://www.reddit.com"),
        ("X (formerly Twitter)", "https://x.com"),
        ("Threads", "https://www.threads.net"),
    ],
}

POLISH_INFOSPHERE_SOURCES: dict[str, list[tuple[str, str]]] = {
    "left": [
        ("Krytyka Polityczna", "https://krytykapolityczna.pl"),
        ("OKO.press", "https://oko.press"),
        ("Krytyka", "https://krytyka.info"),
    ],
    "centrist": [
        ("Polityka", "https://www.polityka.pl"),
        ("Rzeczpospolita", "https://www.rp.pl"),
        ("TVN24", "https://tvn24.pl"),
    ],
    "right": [
        ("Do Rzeczy", "https://dorzeczy.pl"),
        ("wPolityce", "https://wpolityce.pl"),
        ("Gazeta Polska", "https://www.gazetapolska.pl"),
    ],
    "fact": [
        ("Demagog", "https://demagog.org.pl"),
        ("OKO.press Fakt-checking", "https://oko.press/temat/fake-news"),
        ("AFP Sprawdzamy", "https://sprawdzam.afp.com"),
    ],
    "people": [
        ("Reddit", "https://www.reddit.com"),
        ("X (formerly Twitter)", "https://x.com"),
        ("Threads", "https://www.threads.net"),
    ],
}

DEFAULT_MODEL = "gpt-4o-mini"
REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "TAVILY_KEY")


def init_environment() -> logging.Logger:
    """Load environment variables and configure base logging."""
    load_dotenv()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s %(message)s",
    )
    return logging.getLogger("geopoliticai")


def require_env(keys: Sequence[str] = REQUIRED_ENV_VARS) -> None:
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        raise ValueError("Missing required environment variables: " + ", ".join(missing))


def get_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def get_infosphere_sources(infosphere: str) -> dict[str, list[tuple[str, str]]]:
    if infosphere == "english":
        return ENGLISH_INFOSPHERE_SOURCES
    if infosphere == "polish":
        combined: dict[str, list[tuple[str, str]]] = {}
        for key, english_sources in ENGLISH_INFOSPHERE_SOURCES.items():
            merged = english_sources + POLISH_INFOSPHERE_SOURCES.get(key, [])
            seen: set[str] = set()
            unique: list[tuple[str, str]] = []
            for name, url in merged:
                if url in seen:
                    continue
                seen.add(url)
                unique.append((name, url))
            combined[key] = unique
        return combined
    raise ValueError(f"Unsupported infosphere: {infosphere}")
