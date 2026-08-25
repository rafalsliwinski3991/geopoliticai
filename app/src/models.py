"""Shared data structures for the pipeline."""

import operator
import re
from dataclasses import dataclass, field
from typing import Annotated, Literal, TypedDict

_POLISH_DIACRITICS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_POLISH_STOPWORDS = frozenset(
    [
        "czy",
        "jakie",
        "który",
        "która",
        "które",
        "których",
        "ktory",
        "ktora",
        "ktore",
        "ktorych",
        "przez",
        "oraz",
        "tego",
        "jest",
        "się",
        "sie",
        "jako",
        "polska",
        "polskie",
        "polskich",
        "polsce",
        "polski",
        "jakich",
        "jakiego",
        "czemu",
        "skąd",
        "skad",
        "dlaczego",
        "kiedy",
        "gdzie",
        "kto",
        "kogo",
        "komu",
    ]
)


@dataclass
class Source:
    """A source collected from a lane-constrained search."""

    id: str
    title: str
    url: str
    notes: str
    publisher: str | None = None
    published_at: str | None = None
    snippet: str = ""
    content_excerpt: str | None = None
    source_type: str | None = None
    credibility_tier: Literal["A", "B", "C", "D"] | None = None
    lane: Literal["left", "centrist", "right", "people", "fact"] | None = None


@dataclass
class Claim:
    """A source-grounded claim produced by an analyst lane."""

    text: str
    source_ids: list[str]


@dataclass
class FactCheckResult:
    """A verdict and rationale for a single claim."""

    claim: Claim
    verdict: str
    rationale: str


@dataclass
class ResearchPlan:
    """Search plan built before lane searches run."""

    queries: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    timeframe: str = ""
    must_find: list[str] = field(default_factory=list)


@dataclass
class RefereeReport:
    """Result of the referee quality gate."""

    blocked: bool = False
    issues: list[str] = field(default_factory=list)
    unsupported_facts: list[str] = field(default_factory=list)
    loaded_language: list[str] = field(default_factory=list)


class ErrorRecord(TypedDict):
    """One recoverable failure, recorded for operators rather than readers."""

    node: str
    error_type: str
    message: str


def build_error_record(node: str, exc: Exception) -> ErrorRecord:
    """Construct one error record so every node emits the same shape."""
    return {"node": node, "error_type": type(exc).__name__, "message": str(exc)}


class PipelineState(TypedDict):
    """LangGraph state shared by all pipeline nodes."""

    query: str
    language: str
    left_claims: list[Claim]
    centrist_claims: list[Claim]
    right_claims: list[Claim]
    people_claims: list[Claim]
    left_sources: Annotated[list[Source], operator.add]
    centrist_sources: Annotated[list[Source], operator.add]
    right_sources: Annotated[list[Source], operator.add]
    people_sources: Annotated[list[Source], operator.add]
    fact_sources: Annotated[list[Source], operator.add]
    fact_checks: Annotated[list[FactCheckResult], operator.add]
    synthesis: str
    final_output: str
    research_plan: ResearchPlan
    referee_report: RefereeReport
    errors: Annotated[list[ErrorRecord], operator.add]


def detect_language(query: str) -> str:
    """Return 'polish' if the query appears to be in Polish, else 'english'.

    Detection is heuristic:
    1. Any Polish diacritic character → Polish.
    2. Any known Polish function/stop word as a whole token → Polish.
    3. Otherwise → English.
    """
    if any(c in _POLISH_DIACRITICS for c in query):
        return "polish"
    tokens = set(re.findall(r"\b\w+\b", query.lower()))
    if tokens & _POLISH_STOPWORDS:
        return "polish"
    return "english"


def normalize_language(value: str) -> str:
    """Normalize language marker to supported values."""
    return "polish" if str(value).strip().lower() == "polish" else "english"


def normalize_report_mode(value: str) -> str:
    """Normalize and validate the report rendering mode."""
    normalized = str(value).strip().lower()
    if normalized not in {"compact", "full"}:
        raise ValueError("report_mode must be one of: compact, full.")
    return normalized


def build_initial_pipeline_state(
    query: str,
    *,
    language: str,
) -> PipelineState:
    """Return a complete initial pipeline state."""
    normalized_query = " ".join((query or "").split())
    normalized_language = normalize_language(language)
    return {
        "query": normalized_query,
        "language": normalized_language,
        "left_claims": [],
        "centrist_claims": [],
        "right_claims": [],
        "people_claims": [],
        "left_sources": [],
        "centrist_sources": [],
        "right_sources": [],
        "people_sources": [],
        "fact_sources": [],
        "fact_checks": [],
        "synthesis": "",
        "final_output": "",
        "research_plan": ResearchPlan(),
        "referee_report": RefereeReport(),
        "errors": [],
    }
