"""Shared data structures for the pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, TypedDict

_POLISH_DIACRITICS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_POLISH_STOPWORDS = frozenset(
    [
        "czy", "jakie", "który", "która", "które", "których",
        "ktory", "ktora", "ktore", "ktorych",
        "przez", "oraz", "tego", "jest", "się", "sie", "jako",
        "polska", "polskie", "polskich", "polsce", "polski",
        "jakich", "jakiego", "czemu", "skąd", "skad", "dlaczego",
        "kiedy", "gdzie", "kto", "kogo", "komu",
    ]
)


@dataclass
class Source:
    id: str
    title: str
    url: str
    notes: str
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    snippet: str = ""
    content_excerpt: Optional[str] = None
    source_type: Optional[str] = None
    credibility_tier: Optional[Literal["A", "B", "C", "D"]] = None
    lane: Optional[Literal["left", "centrist", "right", "people", "fact"]] = None


@dataclass
class Claim:
    text: str
    source_ids: List[str]


@dataclass
class FactCheckResult:
    claim: Claim
    verdict: str
    rationale: str


@dataclass
class ResearchPlan:
    queries: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    timeframe: str = ""
    must_find: List[str] = field(default_factory=list)


@dataclass
class RefereeReport:
    blocked: bool = False
    issues: List[str] = field(default_factory=list)
    unsupported_facts: List[str] = field(default_factory=list)
    loaded_language: List[str] = field(default_factory=list)
    required_verifications: List[str] = field(default_factory=list)
    required_rewrites: List[str] = field(default_factory=list)


class PipelineState(TypedDict):
    query: str
    language: str
    left_claims: List[Claim]
    centrist_claims: List[Claim]
    right_claims: List[Claim]
    people_claims: List[Claim]
    left_sources: List[Source]
    centrist_sources: List[Source]
    right_sources: List[Source]
    people_sources: List[Source]
    fact_sources: List[Source]
    fact_checks: List[FactCheckResult]
    synthesis: str
    final_output: str
    research_plan: Dict[str, Any]
    referee_report: Dict[str, Any]
    extracted_claims: List[Dict[str, Any]]
    verification_to_do: List[str]
    rewrites_to_do: List[str]
    loop_count: int
    max_loops: int


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


def build_initial_pipeline_state(
    query: str,
    *,
    language: str,
    max_loops: int = 2,
) -> PipelineState:
    """Return a complete initial pipeline state."""
    normalized_query = " ".join((query or "").split())
    normalized_language = normalize_language(language)
    safe_max_loops = max(int(max_loops), 0)
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
        "research_plan": {"queries": [], "entities": [], "timeframe": "", "must_find": []},
        "referee_report": {
            "blocked": False,
            "issues": [],
            "unsupported_facts": [],
            "loaded_language": [],
            "required_verifications": [],
            "required_rewrites": [],
        },
        "extracted_claims": [],
        "verification_to_do": [],
        "rewrites_to_do": [],
        "loop_count": 0,
        "max_loops": safe_max_loops,
    }
