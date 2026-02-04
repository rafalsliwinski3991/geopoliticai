# GeopoliticAI POC (LangGraph)
# Proof-of-concept script that follows MASTER_SYSTEM_PROMPT.md.
# Requires OPENAI_API_KEY and TAVILY_KEY in the environment.
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from typing import Dict, List, Optional, TypedDict, Union

import logging

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from openai import OpenAI
from tavily import TavilyClient

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s %(message)s",
)
logger = logging.getLogger("geopoliticai")

required_keys = ["OPENAI_API_KEY", "TAVILY_KEY"]
missing = [key for key in required_keys if not os.getenv(key)]
if missing:
    raise ValueError("Missing required environment variables: " + ", ".join(missing))

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
openai_client = OpenAI()

LEFTIST_SOURCES = [
    ("Jacobin", "https://jacobin.com"),
    ("Economic Policy Institute", "https://www.epi.org"),
    ("Roosevelt Institute", "https://rooseveltinstitute.org"),
]

CENTRIST_SOURCES = [
    ("Brookings Institution", "https://www.brookings.edu"),
    ("Council on Foreign Relations", "https://www.cfr.org"),
    ("The Economist", "https://www.economist.com"),
]

RIGHTIST_SOURCES = [
    ("American Enterprise Institute", "https://www.aei.org"),
    ("Heritage Foundation", "https://www.heritage.org"),
    ("Hoover Institution", "https://www.hoover.org"),
]

FACT_CHECK_SOURCES = [
    ("Reuters Fact Check", "https://www.reuters.com/fact-check"),
    ("AP Fact Check", "https://apnews.com/hub/ap-fact-check"),
    ("FactCheck.org", "https://www.factcheck.org"),
]


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


def llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
    logger.info("LLM request: model=%s temp=%.2f", MODEL, temperature)
    try:
        response = openai_client.responses.create(
            model=MODEL,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.output_text)
        logger.info("LLM response received via responses API")
        return payload
    except TypeError:
        response = openai_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)
        logger.info("LLM response received via chat.completions API")
        return payload


def _seed_for_agent(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]], agent_key: str
) -> Optional[List[Source]]:
    if isinstance(seed_sources, list):
        return seed_sources
    if isinstance(seed_sources, dict):
        return seed_sources.get(agent_key)
    return None


def _build_biased_query(query: str, references: List[tuple[str, str]]) -> str:
    sites = [url.replace("https://", "").replace("http://", "") for _, url in references]
    site_filter = " OR ".join(f"site:{site}" for site in sites)
    return f"{query} ({site_filter})"


def web_searcher(
    state: PipelineState,
    agent_key: str,
    references: List[tuple[str, str]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> List[Source]:
    seeded = _seed_for_agent(seed_sources, agent_key)
    if seeded:
        logger.info(
            "Web searcher (%s): using seed_sources (%d)", agent_key, len(seeded)
        )
        return seeded

    tavily_key = os.getenv("TAVILY_KEY")
    if not tavily_key:
        raise ValueError("Missing TAVILY_KEY for live search.")

    logger.info("Web searcher (%s): querying Tavily", agent_key)
    client = TavilyClient(api_key=tavily_key)
    biased_query = _build_biased_query(state["query"], references)
    response = client.search(biased_query, max_results=6, search_depth="advanced")
    sources: List[Source] = []
    for idx, item in enumerate(response.get("results", []), start=1):
        notes = (item.get("content") or "").strip().replace("\n", " ")
        source = (
            Source(
                id=f"S{idx}",
                title=(item.get("title") or "Untitled").strip(),
                url=(item.get("url") or "").strip(),
                notes=notes[:240] if notes else "No summary provided.",
            )
        )
        sources.append(source)
        logger.info(
            "Web searcher (%s): source=%s url=%s", agent_key, source.title, source.url
        )

    logger.info("Web searcher (%s): received %d sources", agent_key, len(sources))
    return sources


def build_claims(state: PipelineState, lens: str, sources: List[Source]) -> List[Claim]:
    logger.info("Building claims: lens=%s sources=%d", lens, len(sources))
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in sources
    )
    if lens == "leftist":
        reference_sources = LEFTIST_SOURCES
    elif lens == "centrist":
        reference_sources = CENTRIST_SOURCES
    else:
        reference_sources = RIGHTIST_SOURCES
    reference_block = "\n".join(f"- {name} ({url})" for name, url in reference_sources)
    user = f"""
Query: {state['query']}

Sources:
{source_block}

Preferred references (use for framing; do not invent citations):
{reference_block}

Task: Provide 3-5 analytically cautious claims from the perspective: {lens}.
- Use only the sources provided.
- Each claim must cite one or more source IDs.
Return JSON: {{"claims": [{{"text": "...", "source_ids": ["S1", "S2"]}}]}}.
""".strip()

    data = llm_json(
        system="You are a political analyst who writes precise, source-grounded claims.",
        user=user,
    )
    claims = []
    for item in data.get("claims", []):
        text = (item.get("text") or "").strip()
        source_ids = [sid for sid in item.get("source_ids", []) if isinstance(sid, str)]
        if text:
            claims.append(Claim(text=text, source_ids=source_ids))
    return claims


def leftist_expert(state: PipelineState) -> PipelineState:
    return {
        **state,
        "left_claims": build_claims(state, "leftist", state["left_sources"]),
    }


def centrist_expert(state: PipelineState) -> PipelineState:
    return {
        **state,
        "centrist_claims": build_claims(state, "centrist", state["centrist_sources"]),
    }


def right_expert(state: PipelineState) -> PipelineState:
    return {
        **state,
        "right_claims": build_claims(state, "right-wing", state["right_sources"]),
    }


def fact_checker(state: PipelineState) -> PipelineState:
    logger.info(
        "Fact checking: claims=%d",
        len(state["left_claims"]) + len(state["centrist_claims"]) + len(state["right_claims"]),
    )
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in state["fact_sources"]
    )
    claims = state["left_claims"] + state["centrist_claims"] + state["right_claims"]
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in claims
    )
    reference_block = "\n".join(f"- {name} ({url})" for name, url in FACT_CHECK_SOURCES)
    user = f"""
Sources:
{source_block}

Claims:
{claims_block}

Preferred fact-check references (use for methods; do not invent citations):
{reference_block}

Task: Fact-check each claim against the sources. Use verdicts: TRUE, PARTIALLY TRUE, MISLEADING, FALSE.
Return JSON: {{"results": [{{"claim_text": "...", "verdict": "...", "rationale": "...", "source_ids": ["S1"]}}]}}.
""".strip()

    data = llm_json(
        system="You are a meticulous fact-checker who only uses the provided sources.",
        user=user,
    )

    results: List[FactCheckResult] = []
    for item in data.get("results", []):
        claim_text = (item.get("claim_text") or "").strip()
        verdict = (item.get("verdict") or "").strip()
        rationale = (item.get("rationale") or "").strip()
        source_ids = [sid for sid in item.get("source_ids", []) if isinstance(sid, str)]
        if claim_text and verdict:
            results.append(
                FactCheckResult(
                    claim=Claim(text=claim_text, source_ids=source_ids),
                    verdict=verdict,
                    rationale=rationale,
                )
            )

    return {**state, "fact_checks": results}


def summarizer_judge(state: PipelineState) -> PipelineState:
    logger.info("Summarizing: fact_checks=%d", len(state["fact_checks"]))
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in state["left_claims"] + state["centrist_claims"] + state["right_claims"]
    )
    fact_block = "\n".join(
        f"- {r.verdict}: {r.claim.text} — {r.rationale}" for r in state["fact_checks"]
    )
    user = f"""
Claims:
{claims_block}

Fact checks:
{fact_block}

Task: Provide a neutral synthesis highlighting consensus, disputes, and strongest-supported conclusions.
Return JSON: {{"synthesis": "..."}}.
""".strip()

    data = llm_json(
        system="You are a neutral methodological judge who prioritizes evidence quality.",
        user=user,
    )
    synthesis = (data.get("synthesis") or "").strip()
    return {**state, "synthesis": synthesis}


def render_sources(sources: List[Source]) -> str:
    lines = []
    for s in sources:
        lines.append(f"- [{s.id}] {s.title} ({s.url}) — {s.notes}")
    return "\n".join(lines)


def render_claims(claims: List[Claim]) -> str:
    lines = []
    for c in claims:
        cite = ", ".join(c.source_ids) if c.source_ids else "no sources"
        lines.append(f"- {c.text} (Sources: {cite})")
    return "\n".join(lines)


def render_reference_list(references: List[tuple[str, str]]) -> str:
    return "\n".join(f"- {name} ({url})" for name, url in references)


def render_fact_checks(results: List[FactCheckResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"- {r.verdict}: {r.claim.text} — {r.rationale}")
    return "\n".join(lines)


def _merge_sources(state: PipelineState) -> List[Source]:
    dedup: Dict[str, Source] = {}
    for src in (
        state["left_sources"]
        + state["centrist_sources"]
        + state["right_sources"]
        + state["fact_sources"]
    ):
        if src.url not in dedup:
            dedup[src.url] = src
    return list(dedup.values())


def supervisor_finalize(state: PipelineState) -> PipelineState:
    output: List[str] = []
    output.append("1. 🔎 Factual Background (from Web Searcher)")
    output.append(render_sources(_merge_sources(state)))
    output.append("")
    output.append("2. 🔴 Left Perspective")
    output.append("Preferred references:")
    output.append(render_reference_list(LEFTIST_SOURCES))
    output.append(render_claims(state["left_claims"]))
    output.append("")
    output.append("3. 🟡 Centrist Perspective")
    output.append("Preferred references:")
    output.append(render_reference_list(CENTRIST_SOURCES))
    output.append(render_claims(state["centrist_claims"]))
    output.append("")
    output.append("4. 🔵 Right Perspective")
    output.append("Preferred references:")
    output.append(render_reference_list(RIGHTIST_SOURCES))
    output.append(render_claims(state["right_claims"]))
    output.append("")
    output.append("5. ✅ Fact Check Results")
    output.append("Preferred references:")
    output.append(render_reference_list(FACT_CHECK_SOURCES))
    output.append(render_fact_checks(state["fact_checks"]))
    output.append("")
    output.append("6. ⚖️ Synthesis & Best-Supported Conclusion")
    output.append(state["synthesis"])
    return {**state, "final_output": "\n".join(output)}


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None
):
    graph = StateGraph(PipelineState)

    graph.add_node(
        "left_searcher",
        lambda state: {**state, "left_sources": web_searcher(state, "left", LEFTIST_SOURCES, seed_sources)},
    )
    graph.add_node(
        "centrist_searcher",
        lambda state: {
            **state,
            "centrist_sources": web_searcher(state, "centrist", CENTRIST_SOURCES, seed_sources),
        },
    )
    graph.add_node(
        "right_searcher",
        lambda state: {**state, "right_sources": web_searcher(state, "right", RIGHTIST_SOURCES, seed_sources)},
    )
    graph.add_node(
        "fact_searcher",
        lambda state: {**state, "fact_sources": web_searcher(state, "fact", FACT_CHECK_SOURCES, seed_sources)},
    )
    graph.add_node("left_expert", leftist_expert)
    graph.add_node("centrist_expert", centrist_expert)
    graph.add_node("right_expert", right_expert)
    graph.add_node("fact_checker", fact_checker)
    graph.add_node("summarizer_judge", summarizer_judge)
    graph.add_node("supervisor", supervisor_finalize)

    graph.set_entry_point("left_searcher")
    graph.add_edge("left_searcher", "left_expert")
    graph.add_edge("left_expert", "centrist_searcher")
    graph.add_edge("centrist_searcher", "centrist_expert")
    graph.add_edge("centrist_expert", "right_searcher")
    graph.add_edge("right_searcher", "right_expert")
    graph.add_edge("right_expert", "fact_searcher")
    graph.add_edge("fact_searcher", "fact_checker")
    graph.add_edge("fact_checker", "summarizer_judge")
    graph.add_edge("summarizer_judge", "supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()


def run_pipeline(
    query: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> str:
    app = build_graph(seed_sources)
    initial_state: PipelineState = {
        "query": query,
        "left_claims": [],
        "centrist_claims": [],
        "right_claims": [],
        "left_sources": [],
        "centrist_sources": [],
        "right_sources": [],
        "fact_sources": [],
        "fact_checks": [],
        "synthesis": "",
        "final_output": "",
    }
    result = app.invoke(initial_state)
    return result["final_output"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run GeopoliticAI POC pipeline.")
    parser.add_argument("query", help="Query to analyze")
    args = parser.parse_args()
    print(run_pipeline(args.query))
