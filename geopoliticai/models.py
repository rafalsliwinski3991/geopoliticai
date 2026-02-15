"""Shared data structures for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, TypedDict


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
    lane: Optional[Literal["left", "centrist", "right", "fact"]] = None


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
    left_sources: List[Source]
    centrist_sources: List[Source]
    right_sources: List[Source]
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
