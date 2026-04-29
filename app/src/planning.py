"""Research planning nodes."""

from __future__ import annotations

import logging
import re
from dataclasses import fields
from typing import Any

from pydantic import BaseModel, Field, field_validator

from config import get_model
from llm import invoke_structured_chain
from models import PipelineState, ResearchPlan

logger = logging.getLogger(__name__)
PLANNING_DOMAINS = {
    "geopolitics",
    "economics",
    "social_policy",
    "military",
    "technology",
    "environment",
}
MAX_QUERIES = 5
MIN_QUERIES = 3
MAX_MUST_FIND = 3
MAX_ENTITIES = 8


class ResearchPlanOutput(BaseModel):
    """Structured output for LLM-generated research plans."""

    entities: list[str] = Field(default_factory=list)
    domain: str = "geopolitics"
    queries: list[str] = Field(default_factory=list)
    must_find: list[str] = Field(default_factory=list)

    @field_validator("entities", "queries", "must_find", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, value: Any) -> str:
        domain = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        return domain if domain in PLANNING_DOMAINS else "geopolitics"


def _clean_items(items: list[str], *, limit: int) -> list[str]:
    """Normalize a string list while preserving order and removing duplicates."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = " ".join(str(item).split())
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
        if len(cleaned) >= limit:
            break
    return cleaned


def _research_plan_field_names() -> set[str]:
    """Return fields supported by the current ResearchPlan dataclass."""
    return {field.name for field in fields(ResearchPlan)}


def _make_research_plan(
    *,
    queries: list[str],
    entities: list[str],
    domain: str,
    must_find: list[str],
) -> ResearchPlan:
    """Build ResearchPlan across the current and domain-added model versions."""
    payload: dict[str, Any] = {
        "queries": queries,
        "entities": entities,
        "must_find": must_find,
    }
    if "domain" in _research_plan_field_names():
        payload["domain"] = domain
    return ResearchPlan(**payload)


def _fallback_domain(query: str) -> str:
    """Classify the query with deterministic keyword rules."""
    normalized = query.lower()
    keyword_domains = (
        ("military", ("war", "army", "missile", "nato", "defense", "defence")),
        ("economics", ("tariff", "inflation", "trade", "gdp", "budget", "tax")),
        ("technology", ("ai", "semiconductor", "chip", "cyber", "data", "tech")),
        (
            "environment",
            ("climate", "energy", "emissions", "carbon", "farmland", "water"),
        ),
        (
            "social_policy",
            ("healthcare", "education", "migration", "housing", "welfare"),
        ),
    )
    for domain, keywords in keyword_domains:
        if any(keyword in normalized for keyword in keywords):
            return domain
    return "geopolitics"


def _fallback_entities(query: str) -> list[str]:
    """Extract simple named-entity candidates from the query."""
    candidates = re.findall(
        r"\b[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*)*",
        query,
    )
    return _clean_items(candidates, limit=MAX_ENTITIES)


def _fallback_research_plan(query: str) -> ResearchPlan:
    """Create a deterministic research plan when structured planning fails."""
    domain = _fallback_domain(query)
    queries = _clean_items(
        [
            query,
            f"{query} official data policy background",
            f"{query} economic security implications",
            f"{query} stakeholder response local impact",
            f"{query} legal institutional constraints",
        ],
        limit=MAX_QUERIES,
    )
    must_find = [
        "most relevant recent development",
        "primary-source or official confirmation",
        "clearest policy or public-impact consequence",
    ]
    return _make_research_plan(
        queries=queries,
        entities=_fallback_entities(query),
        domain=domain,
        must_find=must_find,
    )


def _plan_from_output(query: str, output: ResearchPlanOutput) -> ResearchPlan:
    """Normalize LLM output into the project ResearchPlan dataclass."""
    fallback = _fallback_research_plan(query)
    queries = _clean_items(output.queries, limit=MAX_QUERIES)
    if len(queries) < MIN_QUERIES:
        queries = _clean_items(queries + fallback.queries, limit=MAX_QUERIES)
    must_find = _clean_items(output.must_find, limit=MAX_MUST_FIND)
    if not must_find:
        must_find = fallback.must_find
    return _make_research_plan(
        queries=queries,
        entities=_clean_items(output.entities, limit=MAX_ENTITIES),
        domain=output.domain,
        must_find=must_find,
    )


def build_research_plan(state: PipelineState) -> dict[str, Any]:
    """Create an LLM-powered research plan with deterministic fallback."""
    query = state["query"].strip()
    language = state.get("language", "english")
    response_language = "Polish" if language == "polish" else "English"
    try:
        output = invoke_structured_chain(
            schema=ResearchPlanOutput,
            system_prompt=(
                "You are a research planner for multi-perspective political analysis. "
                "Produce search planning data only; do not answer the user's question."
            ),
            human_prompt=(
                "User query:\n{query}\n\n"
                "Response/search language: {response_language}\n\n"
                "Produce:\n"
                "- entities: key people, organizations, countries, policies, or places to track.\n"
                "- domain: exactly one of geopolitics, economics, social_policy, military, technology, environment.\n"
                "- queries: 3-5 semantically diverse web search queries covering different angles. "
                "Do not merely append generic phrases like 'key facts' or 'primary sources'.\n"
                "- must_find: 2-3 specific facts that must be established before final synthesis.\n"
            ),
            variables={"query": query, "response_language": response_language},
            temperature=0.1,
            model=get_model("build_research_plan"),
        )
        plan = _plan_from_output(query, ResearchPlanOutput.model_validate(output))
    except Exception as exc:
        logger.warning("Research planning LLM failed; using fallback plan: %s", exc)
        plan = _fallback_research_plan(query)
    return {"research_plan": plan}
