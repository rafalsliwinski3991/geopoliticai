"""Helpers for reading LangGraph runtime configuration inside nodes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from config import get_infosphere_sources
from models import PipelineState, normalize_language

InfosphereSources = dict[str, list[tuple[str, str]]]


def configurable(config: RunnableConfig | None) -> dict[str, Any]:
    """Return the LangGraph configurable mapping, if present."""
    if config is None or not isinstance(config, Mapping):
        return {}
    raw = config.get("configurable", {})
    return raw if isinstance(raw, dict) else {}


def runtime_language(state: PipelineState, config: RunnableConfig | None) -> str:
    """Resolve the request language from config, falling back to state."""
    raw = configurable(config).get("language", state.get("language", "english"))
    return normalize_language(str(raw))


def runtime_infosphere_sources(
    state: PipelineState,
    config: RunnableConfig | None,
) -> InfosphereSources:
    """Resolve lane source configuration from LangGraph runtime config."""
    raw = configurable(config).get("infosphere_sources")
    if isinstance(raw, dict):
        return cast(InfosphereSources, raw)
    return get_infosphere_sources(runtime_language(state, config))


def runtime_report_mode(config: RunnableConfig | None, default: str = "full") -> str:
    """Resolve report rendering mode from LangGraph runtime config."""
    raw = configurable(config).get("report_mode", default)
    return str(raw).strip().lower()
