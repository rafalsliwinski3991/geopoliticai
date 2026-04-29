"""Research-planning node wrapper."""

from __future__ import annotations

from typing import Any

from models import PipelineState
from planning import build_research_plan


def build_research_plan_step(state: PipelineState) -> dict[str, Any]:
    """Build a source-search plan for the request."""
    return build_research_plan(state)
