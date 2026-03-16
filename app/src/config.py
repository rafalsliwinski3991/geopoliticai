"""Configuration helpers and constants for the GeopoliticAI pipeline."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

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
DEFAULT_ANALYST_ADDITIONAL_SOURCES = 0
DEFAULT_OPENAI_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 1200
REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "BRAVE_SEARCH_KEY")

AGENT_MODEL_NAMES: dict[str, str] = {
    "left_analyst": "gpt-4o-mini",
    "center_analyst": "gpt-4o-mini",
    "right_analyst": "gpt-4o-mini",
    "people_analyst": "gpt-4o-mini",
    "cross_check_facts": "gpt-4o-mini",
    "compose_final": "gpt-4o-mini",
    # Lane aliases used by search helpers.
    "left": "gpt-4o-mini",
    "centrist": "gpt-4o-mini",
    "right": "gpt-4o-mini",
    "people": "gpt-4o-mini",
    "fact": "gpt-4o-mini",
}


def init_environment(log_level: str | None = None) -> logging.Logger:
    """Load environment variables and configure base logging."""
    load_dotenv()
    configured_level = (log_level or os.getenv("LOG_LEVEL", "INFO")).upper().strip()
    numeric_level = logging.getLevelName(configured_level)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logging.basicConfig(
        level=numeric_level,
        format="%(levelname)s %(message)s",
        force=True,
    )
    # Keep third-party transport logs quiet unless explicitly requested via DEBUG.
    for noisy_logger in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    return logging.getLogger("agent")


def require_env(keys: Sequence[str] = REQUIRED_ENV_VARS) -> None:
    """Ensure required environment variables are present."""
    missing = [key for key in keys if not os.getenv(key)]
    if missing:
        raise ValueError("Missing required environment variables: " + ", ".join(missing))


def _get_non_negative_int_env(var_name: str, default: int) -> int:
    """Read a non-negative integer env var, falling back to default when invalid."""
    raw_value = os.getenv(var_name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = int(raw_value.strip())
    except ValueError:
        logger.warning(
            "Invalid %s=%r; expected an integer. Falling back to %d.",
            var_name,
            raw_value,
            default,
        )
        return default
    if parsed < 0:
        logger.warning(
            "Invalid %s=%r; expected a non-negative integer. Falling back to %d.",
            var_name,
            raw_value,
            default,
        )
        return default
    return parsed


def _get_positive_int_env(var_name: str, default: int) -> int:
    """Read a positive integer env var, falling back to default when invalid."""
    raw_value = os.getenv(var_name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = int(raw_value.strip())
    except ValueError:
        logger.warning(
            "Invalid %s=%r; expected an integer. Falling back to %d.",
            var_name,
            raw_value,
            default,
        )
        return default
    if parsed <= 0:
        logger.warning(
            "Invalid %s=%r; expected a positive integer. Falling back to %d.",
            var_name,
            raw_value,
            default,
        )
        return default
    return parsed


def _get_positive_float_env(var_name: str, default: float) -> float:
    """Read a positive float env var, falling back to default when invalid."""
    raw_value = os.getenv(var_name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = float(raw_value.strip())
    except ValueError:
        logger.warning(
            "Invalid %s=%r; expected a float. Falling back to %.2f.",
            var_name,
            raw_value,
            default,
        )
        return default
    if parsed <= 0:
        logger.warning(
            "Invalid %s=%r; expected a positive float. Falling back to %.2f.",
            var_name,
            raw_value,
            default,
        )
        return default
    return parsed


def get_analyst_additional_sources() -> int:
    """Return how many optional extra sources each analyst may use."""
    return _get_non_negative_int_env(
        "ANALYST_ADDITIONAL_SOURCES",
        DEFAULT_ANALYST_ADDITIONAL_SOURCES,
    )


def get_openai_timeout_seconds() -> float:
    """Return timeout used for OpenAI API calls."""
    return _get_positive_float_env(
        "OPENAI_TIMEOUT_SECONDS",
        DEFAULT_OPENAI_TIMEOUT_SECONDS,
    )


def get_openai_max_output_tokens() -> int:
    """Return max output tokens used for OpenAI API calls."""
    return _get_positive_int_env(
        "OPENAI_MAX_OUTPUT_TOKENS",
        DEFAULT_OPENAI_MAX_OUTPUT_TOKENS,
    )


def get_model(agent_key: str | None = None) -> str:
    """Return the configured OpenAI model, optionally overridden per agent key."""
    base_model = os.getenv("OPENAI_MODEL")
    fallback = base_model.strip() if base_model and base_model.strip() else DEFAULT_MODEL
    if not agent_key:
        return fallback

    return AGENT_MODEL_NAMES.get(agent_key.strip().lower(), fallback)


def get_infosphere_sources(infosphere: str) -> dict[str, list[tuple[str, str]]]:
    """Return the sources list for the requested infosphere."""
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
