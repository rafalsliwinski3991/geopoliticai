"""Configuration helpers and constants for the GeopoliticAI pipeline."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import TypeVar

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
T = TypeVar("T")

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
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 4096
DEFAULT_RATE_LIMIT_REQUESTS = 20
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
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
    env_log_level = os.getenv("LOG_LEVEL") or "INFO"
    configured_level = (log_level or env_log_level).upper().strip()
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
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )


def _get_env_var(
    var_name: str,
    default: T,
    *,
    parser: Callable[[str], T],
    validator: Callable[[T], bool],
    expected_type: str,
    expected_value: str,
    default_format: str,
) -> T:
    """Read and validate an environment variable, falling back to default."""
    raw_value = os.getenv(var_name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = parser(raw_value.strip())
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid %s=%r; expected {expected_type}. Falling back to {default_format}.",
            var_name,
            raw_value,
            default,
        )
        return default
    if not validator(parsed):
        logger.warning(
            f"Invalid %s=%r; expected {expected_value}. Falling back to {default_format}.",
            var_name,
            raw_value,
            default,
        )
        return default
    return parsed


def get_analyst_additional_sources() -> int:
    """Return how many optional extra sources each analyst may use."""
    return _get_env_var(
        "ANALYST_ADDITIONAL_SOURCES",
        DEFAULT_ANALYST_ADDITIONAL_SOURCES,
        parser=int,
        validator=lambda value: value >= 0,
        expected_type="an integer",
        expected_value="a non-negative integer",
        default_format="%d",
    )


def get_openai_timeout_seconds() -> float:
    """Return timeout used for OpenAI API calls."""
    return _get_env_var(
        "OPENAI_TIMEOUT_SECONDS",
        DEFAULT_OPENAI_TIMEOUT_SECONDS,
        parser=float,
        validator=lambda value: value > 0,
        expected_type="a float",
        expected_value="a positive float",
        default_format="%.2f",
    )


def get_openai_max_output_tokens() -> int:
    """Return max output tokens used for OpenAI API calls."""
    return _get_env_var(
        "OPENAI_MAX_OUTPUT_TOKENS",
        DEFAULT_OPENAI_MAX_OUTPUT_TOKENS,
        parser=int,
        validator=lambda value: value > 0,
        expected_type="an integer",
        expected_value="a positive integer",
        default_format="%d",
    )


def get_rate_limit_requests() -> int:
    """Return the max number of API requests allowed per rate-limit window."""
    return _get_env_var(
        "API_RATE_LIMIT_REQUESTS",
        DEFAULT_RATE_LIMIT_REQUESTS,
        parser=int,
        validator=lambda value: value > 0,
        expected_type="an integer",
        expected_value="a positive integer",
        default_format="%d",
    )


def get_rate_limit_window_seconds() -> int:
    """Return the rolling window size (seconds) used by the API rate limiter."""
    return _get_env_var(
        "API_RATE_LIMIT_WINDOW_SECONDS",
        DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        parser=int,
        validator=lambda value: value > 0,
        expected_type="an integer",
        expected_value="a positive integer",
        default_format="%d",
    )


def get_model(agent_key: str | None = None) -> str:
    """Return the configured OpenAI model, optionally overridden per agent key."""
    base_model = os.getenv("OPENAI_MODEL")
    fallback = (
        base_model.strip() if base_model and base_model.strip() else DEFAULT_MODEL
    )
    if not agent_key:
        return fallback

    return AGENT_MODEL_NAMES.get(agent_key.strip().lower(), fallback)


def get_infosphere_sources(infosphere: str) -> dict[str, list[tuple[str, str]]]:
    """Return the sources list for the requested infosphere.

    Polish infosphere uses only Polish-language sources.
    English infosphere uses only English-language sources.
    """
    if infosphere == "english":
        return ENGLISH_INFOSPHERE_SOURCES
    if infosphere == "polish":
        return POLISH_INFOSPHERE_SOURCES
    raise ValueError(f"Unsupported infosphere: {infosphere}")
