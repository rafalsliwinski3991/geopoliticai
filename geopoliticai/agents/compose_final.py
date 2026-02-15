from __future__ import annotations

from geopoliticai.models import PipelineState
from geopoliticai.summarizer import summarizer_judge


def compose_final_agent(state: PipelineState, language: str) -> PipelineState:
    return summarizer_judge(state, language)
