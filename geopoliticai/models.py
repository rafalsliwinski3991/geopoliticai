"""Shared data structures for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, TypedDict


@dataclass
class Source:
    id: str
    title: str
    url: str
    notes: str


@dataclass
class Claim:
    text: str
    source_ids: List[str]


@dataclass
class FactCheckResult:
    claim: Claim
    verdict: str
    rationale: str


class PipelineState(TypedDict):
    query: str
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
