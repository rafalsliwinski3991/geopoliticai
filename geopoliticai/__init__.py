"""GeopoliticAI proof-of-concept pipeline."""

from __future__ import annotations

from typing import Any


def run_pipeline(*args: Any, **kwargs: Any) -> str:
    """Lazily import and execute the pipeline."""
    from geopoliticai.graph import run_pipeline as _run_pipeline

    return _run_pipeline(*args, **kwargs)


__all__ = ["run_pipeline"]
