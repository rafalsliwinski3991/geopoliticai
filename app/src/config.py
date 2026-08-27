"""Environment and model configuration shared by all pipelines."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "BRAVE_SEARCH_KEY")


@dataclass(frozen=True)
class LLMSettings:
    """Hardcoded model/timeout/token knobs for one OpenAI call site.

    A shared default lives here as `DEFAULT_LLM_SETTINGS`. An agent that
    wants different values for a specific node (a different model, a longer
    timeout) builds its own `LLMSettings(...)` in its own `config.py` and
    passes it through instead.
    """

    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    timeout_seconds: float = 60.0
    max_output_tokens: int = 16_384


DEFAULT_LLM_SETTINGS = LLMSettings()

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
