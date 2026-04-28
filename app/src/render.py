"""Rendering utilities for pipeline output."""

from __future__ import annotations

from models import PipelineState, Source


def merge_sources(state: PipelineState) -> list[Source]:
    """Return all collected sources deduplicated by URL."""
    dedup: dict[str, Source] = {}
    for src in (
        state["left_sources"]
        + state["centrist_sources"]
        + state["right_sources"]
        + state["people_sources"]
        + state["fact_sources"]
    ):
        if src.url not in dedup:
            dedup[src.url] = src
    return list(dedup.values())
