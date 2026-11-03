"""Specialist tools for the supervisor orchestrator."""

from agents.orchestrator.tools.deep_expert import run_deep_expert
from agents.orchestrator.tools.deep_forecaster import run_deep_forecaster
from agents.orchestrator.tools.document import run_document
from agents.orchestrator.tools.expert import run_expert
from agents.orchestrator.tools.reporter import run_reporter

RESEARCH_TOOLS = [run_expert, run_deep_expert, run_deep_forecaster, run_reporter]
DOCUMENT_TOOLS = [run_document]
ALL_TOOLS = [*RESEARCH_TOOLS, *DOCUMENT_TOOLS]

__all__ = [
    "ALL_TOOLS",
    "DOCUMENT_TOOLS",
    "RESEARCH_TOOLS",
    "run_deep_expert",
    "run_deep_forecaster",
    "run_document",
    "run_expert",
    "run_reporter",
]
