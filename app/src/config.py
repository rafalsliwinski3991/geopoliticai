"""Environment and model configuration shared by all pipelines."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
T = TypeVar("T")

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 16_384
REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "BRAVE_SEARCH_KEY")

# app/src/config.py -> app/src -> app -> repo root. Resolved explicitly so
# every entrypoint (CLI, API, tests, langgraph dev) reads the same
# repo-root .env that Docker Compose's `env_file: .env` also uses,
# regardless of the caller's current working directory.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


def init_environment(log_level: str | None = None) -> logging.Logger:
    """Load environment variables and configure base logging."""
    load_dotenv(_REPO_ROOT_ENV)
    env_log_level = os.getenv("LOG_LEVEL") or "INFO"
    configured_level = (log_level or env_log_level).upper().strip()
    numeric_level = logging.getLevelName(configured_level)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logging.basicConfig(
        level=numeric_level, format="%(levelname)s %(message)s", force=True
    )
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
            "Invalid %s=%r; expected %s. Falling back to %s.",
            var_name,
            raw_value,
            expected_type,
            default_format % default,
        )
        return default
    if not validator(parsed):
        logger.warning(
            "Invalid %s=%r; expected %s. Falling back to %s.",
            var_name,
            raw_value,
            expected_value,
            default_format % default,
        )
        return default
    return parsed


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


def get_model() -> str:
    """Return the configured OpenAI model."""
    base_model = os.getenv("OPENAI_MODEL")
    return base_model.strip() if base_model and base_model.strip() else DEFAULT_MODEL
