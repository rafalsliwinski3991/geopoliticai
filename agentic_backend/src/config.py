"""Environment and model configuration shared by all pipelines."""

from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# The delivery layer's transport cap: at most this much text reaches the browser
# (api._generate clips at it). `nodes.verify` refuses an answer that would not
# survive the clip (review thread, #143).
MAX_ANSWER_CHARS = 50_000

REQUIRED_ENV_VARS = (
    "OPENAI_API_KEY",
    "BRAVE_SEARCH_KEY",
    "JWT_SIGNING_KEY",
    # The forecaster's council seats (all seven, via OpenRouter) and its video
    # reading (Gemini, called directly; brainstorm 2026Sep30 Q4, Q26, F10): a
    # forecast without the first has no council and without the second loses
    # `ask_video`, so the API does not start.
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
)
# Checked at startup, never at import: `langgraph dev` and the unit suite run
# `build_graph()` with no checkpointer and patch `require_env` where needed,
# but the API must not come up unable to authenticate anyone (§1.6, fail closed).

# The daily research-turn quota (flag 1): a named constant, never a literal.
# DAILY_RESEARCH_TURNS bounds one account's spending; it does not bound the
# operator's bill, because signup is public and nothing caps the number of
# accounts. The site-wide ceiling is its own `site_quota` table (one row per
# UTC day), spent by INCREMENT_SITE_QUOTA just before the caller's own count.
DAILY_RESEARCH_TURNS = 50
DAILY_RESEARCH_TURNS_ALL_USERS = 2500
# A deep-expert turn costs roughly 10-30x an expert turn, so it spends this many
# units from both counters (brainstorm 2026Sep28 Q3; review decision 2026Sep30:
# 10, not 5, keeps one deep turn from crowding out an expert user's whole day).
DEEP_RESEARCH_TURN_COST = 10
# A forecast (agents/deep_forecaster/) spends this many of a user's daily units:
# research over the forecasters' sites, a 7-member council voting twice, and up to 14 minutes
# of wall time (brainstorm 2026Sep30 Q22, Q25). Follow-ups are ordinary turns.
FORECAST_TURN_COST = 20
SUPPORTED_ARIZE_PLATFORMS = frozenset({"AX", "PHOENIX"})
LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "[thread=%(thread_id)s user=%(user_id)s] %(message)s"
)
LOG_UNBOUND = "-"
# Set once per request in api.py; read by LogContextFilter on every record.
LOG_THREAD_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "log_thread_id", default=None
)
LOG_USER_ID: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "log_user_id", default=None
)


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
    # OpenAI reasoning effort for the models that take it (o*, gpt-5*). None
    # keeps the API default and is what every existing call site means: only an
    # agent that drives its own tool loop sets this, where per-turn latency is
    # the wall-clock budget (smoke run 2026-09-29).
    reasoning_effort: str | None = None


DEFAULT_LLM_SETTINGS = LLMSettings()

# agentic_backend/src/config.py -> agentic_backend/src -> agentic_backend ->
# repo root. Resolved explicitly so
# every entrypoint (API, tests, langgraph dev) reads the same
# repo-root .env that Docker Compose's `env_file: .env` also uses,
# regardless of the caller's current working directory.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


def get_trace_endpoint() -> str | None:
    """Select the configured collector endpoint for the active platform."""
    platform = get_arize_platform()
    endpoint_variable = (
        "ARIZE_COLLECTOR_ENDPOINT" if platform == "AX" else "PHOENIX_COLLECTOR_ENDPOINT"
    )
    return os.getenv(endpoint_variable)


def get_arize_platform() -> str:
    """Return the configured tracing platform, defaulting to Phoenix."""
    platform = (os.getenv("ARIZE_PLATFORM") or "PHOENIX").strip().upper()
    if platform not in SUPPORTED_ARIZE_PLATFORMS:
        supported = ", ".join(sorted(SUPPORTED_ARIZE_PLATFORMS))
        raise ValueError(f"ARIZE_PLATFORM must be one of {supported}; got {platform!r}")
    return platform


def bind_log_context(
    *, thread_id: str | None = None, user_id: int | None = None
) -> None:
    """Tag every log line this request produces from here on."""
    if thread_id is not None:
        LOG_THREAD_ID.set(thread_id)
    if user_id is not None:
        LOG_USER_ID.set(user_id)


class LogContextFilter(logging.Filter):
    """Stamp the request's thread and user onto each record; never drop one."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach `thread_id` and `user_id` (or the placeholder) to the record."""
        thread_id = LOG_THREAD_ID.get()
        user_id = LOG_USER_ID.get()
        record.thread_id = thread_id if thread_id is not None else LOG_UNBOUND
        record.user_id = user_id if user_id is not None else LOG_UNBOUND
        return True


def init_environment(log_level: str | None = None) -> logging.Logger:
    """Load environment variables and configure base logging."""
    load_dotenv(_REPO_ROOT_ENV)
    env_log_level = os.getenv("LOG_LEVEL") or "INFO"
    configured_level = (log_level or env_log_level).upper().strip()
    numeric_level = logging.getLevelName(configured_level)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logging.basicConfig(level=numeric_level, format=LOG_FORMAT, force=True)
    # Handler filters (not logger filters) see every propagated record.
    for handler in logging.getLogger().handlers:
        handler.addFilter(LogContextFilter())
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
