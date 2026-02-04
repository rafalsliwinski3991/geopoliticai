"""Configuration helpers and constants for the GeopoliticAI pipeline."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from dotenv import load_dotenv

LEFTIST_SOURCES = [
    ("Jacobin", "https://jacobin.com"),
    ("Economic Policy Institute", "https://www.epi.org"),
    ("Roosevelt Institute", "https://rooseveltinstitute.org"),
]

CENTRIST_SOURCES = [
    ("Brookings Institution", "https://www.brookings.edu"),
    ("Council on Foreign Relations", "https://www.cfr.org"),
    ("The Economist", "https://www.economist.com"),
]

RIGHTIST_SOURCES = [
    ("American Enterprise Institute", "https://www.aei.org"),
    ("Heritage Foundation", "https://www.heritage.org"),
    ("Hoover Institution", "https://www.hoover.org"),
]

FACT_CHECK_SOURCES = [
    ("Reuters Fact Check", "https://www.reuters.com/fact-check"),
    ("AP Fact Check", "https://apnews.com/hub/ap-fact-check"),
    ("FactCheck.org", "https://www.factcheck.org"),
]

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
