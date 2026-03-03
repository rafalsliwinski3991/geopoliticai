"""Compose the final synthesis from claims and fact-check results."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, field_validator

from geopoliticai.config import get_model
from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import PipelineState

logger = logging.getLogger(__name__)


class SynthesisOutput(BaseModel):
    """Structured output for the synthesis step."""

    synthesis: str = ""

    @field_validator("synthesis", mode="before")
    @classmethod
    def _coerce_synthesis_to_text(cls, value: Any) -> str:
        """Normalize non-string synthesis payloads into text."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            lines: list[str] = []
            for key, nested in value.items():
                label = key.replace("_", " ").strip().capitalize()
                if isinstance(nested, str):
                    lines.append(f"{label}: {nested}")
                else:
                    lines.append(f"{label}: {json.dumps(nested, ensure_ascii=False)}")
            return "\n".join(lines)
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return str(value)


def _looks_generic_synthesis(text: str) -> bool:
    """Heuristically detect templated or placeholder-heavy synthesis text."""
    lowered = text.lower()
    if not text.strip():
        return True
    generic_phrases = [
        "one claim states",
        "another claim asserts",
        "overall, while",
        "the claims presented",
        "some claims are robustly",
        "mixed evidence",
    ]
    if any(phrase in lowered for phrase in generic_phrases):
        return True
    # Treat explicit template markers as suspicious, but avoid lower-case false positives.
    placeholder_hits = re.findall(r"\b[XYZABC]\b", text)
    if len(placeholder_hits) >= 2:
        return True
    if re.search(r"\b(?:claim|option|source|fact)\s+[XYZABC]\b", text):
        return True
    return False


def _split_synthesis_lines(text: str) -> tuple[str, list[str]]:
    """Split synthesis into first answer line and remaining detail lines."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", []
    return lines[0], lines[1:]


def _has_synthesis_details(text: str) -> bool:
    """Require at least one non-trivial detail line after the short answer."""
    _, details = _split_synthesis_lines(text)
    if not details:
        return False
    return len(" ".join(details).strip()) >= 24


def _all_claims(state: PipelineState) -> list:
    return (
        state["left_claims"]
        + state["centrist_claims"]
        + state["right_claims"]
        + state["people_claims"]
    )


def _infer_who_started_answer(query: str, state: PipelineState) -> str:
    """Infer likely initiating side for 'who started ... between A and B' queries."""
    lowered_query = query.lower()
    if "who started" not in lowered_query or " between " not in lowered_query:
        return ""
    between_match = re.search(
        r"between\s+(.+?)\s+and\s+(.+?)(?:\s+(?:in|on|during)\b|[?.!,]|$)",
        lowered_query,
    )
    if not between_match:
        return ""

    left_side = between_match.group(1).strip()
    right_side = between_match.group(2).strip()
    if not left_side or not right_side:
        return ""

    split_pattern = r"\s*(?:/|,|&|\+|\bor\b|\band\b)\s*"
    left_terms = [term for term in re.split(split_pattern, left_side) if term]
    right_terms = [term for term in re.split(split_pattern, right_side) if term]
    if not left_terms or not right_terms:
        return ""

    evidence_texts = [
        claim.text for claim in _all_claims(state) if claim.text.strip()
    ] + [
        src.notes
        for src in (
            state["left_sources"]
            + state["centrist_sources"]
            + state["right_sources"]
            + state["people_sources"]
            + state["fact_sources"]
        )
        if src.notes.strip()
    ]

    start_markers = (
        "started",
        "began",
        "launched",
        "initiated",
        "first strike",
        "first strikes",
        "opening strike",
        "opened fire",
    )
    left_hits = 0
    right_hits = 0
    for text in evidence_texts:
        lowered = text.lower()
        if not any(marker in lowered for marker in start_markers):
            continue
        has_left = any(term in lowered for term in left_terms)
        has_right = any(term in lowered for term in right_terms)
        if has_left and not has_right:
            left_hits += 1
        elif has_right and not has_left:
            right_hits += 1

    if left_hits >= 2 and left_hits > right_hits:
        return f"{left_side.title()} initiated the first reported strikes; {right_side.title()} appears to have responded."
    if right_hits >= 2 and right_hits > left_hits:
        return f"{right_side.title()} initiated the first reported strikes; {left_side.title()} appears to have responded."
    return ""


def _infer_yes_no_answer(query: str, state: PipelineState) -> tuple[str, str]:
    """Infer a direct answer for simple 'Is X in Y?' queries from gathered evidence."""
    match = re.match(r"^\s*is\s+(.+?)\s+in\s+([^?]+)\??\s*$", query, flags=re.IGNORECASE)
    if not match:
        return "UNCLEAR", ""

    subject = match.group(1).strip().lower()
    location = match.group(2).strip().lower()
    if not subject or not location:
        return "UNCLEAR", ""

    evidence_texts = [
        claim.text for claim in _all_claims(state) if claim.text.strip()
    ] + [
        src.notes
        for src in (
            state["left_sources"]
            + state["centrist_sources"]
            + state["right_sources"]
            + state["people_sources"]
            + state["fact_sources"]
        )
        if src.notes.strip()
    ]

    positive = 0
    negative = 0
    for text in evidence_texts:
        lowered = text.lower()
        if subject not in lowered or location not in lowered:
            continue
        if re.search(rf"\bnot\b[^.]*\b{re.escape(location)}\b", lowered):
            negative += 1
            continue
        positive += 1

    if positive > negative and positive > 0:
        return "YES", f"{subject.title()} is in {location.title()}."
    if negative > positive and negative > 0:
        return "NO", f"{subject.title()} is not in {location.title()}."
    return "UNCLEAR", ""


def _fallback_synthesis(state: PipelineState, language: str) -> str:
    """Build a deterministic, user-friendly synthesis when LLM output is generic."""
    query = state["query"]
    answer_label, answer_text = _infer_yes_no_answer(query, state)
    who_started_answer = _infer_who_started_answer(query, state)
    claim_with_author: list[tuple[str, Any]] = []
    claim_with_author.extend(("Left", claim) for claim in state["left_claims"])
    claim_with_author.extend(("Centrist", claim) for claim in state["centrist_claims"])
    claim_with_author.extend(("Right", claim) for claim in state["right_claims"])
    claim_with_author.extend(("People", claim) for claim in state["people_claims"])

    claim_verdicts: dict[str, tuple[str, str]] = {}
    for fact_check in state["fact_checks"]:
        claim_verdicts[fact_check.claim.text] = (
            fact_check.verdict,
            fact_check.rationale,
        )

    if language == "polish":
        if who_started_answer:
            lead = f"Krotka odpowiedz: {who_started_answer}"
        elif answer_label == "YES":
            lead = f"Krotka odpowiedz: Tak. {answer_text}"
        elif answer_label == "NO":
            lead = f"Krotka odpowiedz: Nie. {answer_text}"
        else:
            lead = (
                "Krotka odpowiedz: Niejednoznaczne na podstawie obecnych danych."
            )
        fact_status = (
            f"Weryfikacja: {len(state['fact_checks'])} twierdzen sprawdzonych."
            if state["fact_checks"]
            else "Brak wynikow fact-checkingu."
        )
        claims_header = "Twierdzenia wg perspektyw:"
        no_claims_line = "- Nie wygenerowano twierdzen."
    else:
        if who_started_answer:
            lead = f"Short answer: {who_started_answer}"
        elif answer_label == "YES":
            lead = f"Short answer: Yes. {answer_text}"
        elif answer_label == "NO":
            lead = f"Short answer: No. {answer_text}"
        else:
            lead = "Short answer: Unclear from the currently gathered evidence."
        fact_status = (
            f"Verification: {len(state['fact_checks'])} claims fact-checked."
            if state["fact_checks"]
            else "No fact-check verdicts were produced."
        )
        claims_header = "Claims by perspective:"
        no_claims_line = "- No claims were generated."

    claim_lines: list[str] = []
    for author, claim in claim_with_author:
        text = claim.text.strip()
        if not text:
            continue
        short_text = text[:200] + ("..." if len(text) > 200 else "")
        sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
        if text in claim_verdicts:
            verdict, rationale = claim_verdicts[text]
            short_rationale = rationale[:120] + ("..." if len(rationale) > 120 else "")
            claim_lines.append(
                f"- [{author}] {short_text}\n"
                f"  Verdict: {verdict} | {short_rationale} | Sources: {sources}"
            )
        else:
            claim_lines.append(
                f"- [{author}] {short_text}\n"
                f"  Verdict: NOT CHECKED | Sources: {sources}"
            )

    parts = [lead, fact_status, claims_header]
    if claim_lines:
        parts.extend(claim_lines)
    else:
        parts.append(no_claims_line)
    return "\n".join(parts)


def _ensure_synthesis_has_details(
    synthesis: str, state: PipelineState, language: str
) -> str:
    """Guarantee synthesis includes rationale details, not only a short answer line."""
    cleaned = synthesis.strip()
    if _has_synthesis_details(cleaned):
        return cleaned

    fallback = _fallback_synthesis(state, language).strip()
    if not fallback:
        return cleaned

    lead, _ = _split_synthesis_lines(cleaned)
    _, fallback_details = _split_synthesis_lines(fallback)
    if lead and fallback_details:
        return "\n".join([lead, *fallback_details])
    return fallback


def compose_final_agent(state: PipelineState, language: str) -> PipelineState:
    """Generate the final synthesis summary for the report."""
    if not (
        state["left_claims"]
        or state["centrist_claims"]
        or state["right_claims"]
        or state["people_claims"]
    ):
        logger.warning("Compose final: no analyst claims available for synthesis.")
    else:
        logger.info(
            "Compose final: claims counts left=%d centrist=%d right=%d people=%d.",
            len(state["left_claims"]),
            len(state["centrist_claims"]),
            len(state["right_claims"]),
            len(state["people_claims"]),
        )
    claims = _all_claims(state)
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in claims
    )
    true_checks = [r for r in state["fact_checks"] if r.verdict.upper() == "TRUE"]
    partial_checks = [
        r for r in state["fact_checks"] if r.verdict.upper() == "PARTIALLY TRUE"
    ]
    fact_block = "\n".join(
        f"- {r.verdict}: {r.claim.text} — {r.rationale}"
        for r in (true_checks + partial_checks)
    )
    true_claims_block = "\n".join(
        f"- {r.claim.text} (Sources: {', '.join(r.claim.source_ids) if r.claim.source_ids else 'none'})"
        for r in (true_checks + partial_checks)
    )
    response_language = "Polish" if language == "polish" else "English"
    fact_status = (
        "Fact-check verdicts are available."
        if state["fact_checks"]
        else "No fact-check verdicts are available."
    )
    model_name = get_model("compose_final")

    data = invoke_structured_chain(
        schema=SynthesisOutput,
        system_prompt="You are a neutral methodological judge who prioritizes evidence quality.",
        human_prompt=(
            "User query: {query}\n\n"
            "All claims:\n{claims_block}\n\n"
            "Fact checks (TRUE/PARTIALLY TRUE):\n{fact_block}\n\n"
            "Verified claims:\n{true_claims_block}\n\n"
            "Fact-check status: {fact_status}\n\n"
            "Task: Provide a user-friendly synthesis that directly answers the user query.\n"
            "Requirements:\n"
            "- Write in {response_language}.\n"
            "- First line must be: 'Short answer: ...'.\n"
            "- Give a direct answer in plain language.\n"
            "- If fact-check verdicts are available, prioritize them.\n"
            "- If fact-check verdicts are unavailable, use consensus from source-grounded claims and explicitly say this.\n"
            "- Mention at least 2 concrete facts when available; if fewer exist, use what is available.\n"
            "- Include source IDs in parentheses when possible, e.g., (Sources: S1, S3).\n"
            "- Do not use placeholders like X/Y/Z/A/B or generic templates.\n"
            "Return a JSON object with exactly one key: synthesis (string)."
        ),
        variables={
            "query": state["query"],
            "claims_block": claims_block,
            "fact_block": fact_block,
            "true_claims_block": true_claims_block,
            "fact_status": fact_status,
            "response_language": response_language,
        },
        temperature=0.2,
        model=model_name,
    )
    synthesis = data.synthesis.strip()
    logger.debug("Compose final: received synthesis len=%d", len(synthesis))
    if _looks_generic_synthesis(synthesis) or not _has_synthesis_details(synthesis):
        logger.info("Compose final: synthesis too generic/thin; retrying with stricter prompt.")
        retry = invoke_structured_chain(
            schema=SynthesisOutput,
            system_prompt="You are a neutral methodological judge who prioritizes evidence quality.",
            human_prompt=(
                "User query: {query}\n\n"
                "All claims:\n{claims_block}\n\n"
                "Fact checks (TRUE/PARTIALLY TRUE):\n{fact_block}\n\n"
                "Verified claims:\n{true_claims_block}\n\n"
                "Fact-check status: {fact_status}\n\n"
                "Task: Provide a synthesis that answers the user query directly and clearly.\n"
                "Requirements:\n"
                "- Write in {response_language}.\n"
                "- First line must be: 'Short answer: ...'.\n"
                "- Use concise plain language.\n"
                "- If fact-check verdicts are unavailable, explicitly state that this is a claim-consensus answer.\n"
                "- Mention concrete facts when available.\n"
                "- Include source IDs in parentheses when possible.\n"
                "- Strictly avoid placeholders or templated prose.\n"
                "Return a JSON object with exactly one key: synthesis (string)."
            ),
            variables={
                "query": state["query"],
                "claims_block": claims_block,
                "fact_block": fact_block,
                "true_claims_block": true_claims_block,
                "fact_status": fact_status,
                "response_language": response_language,
            },
            temperature=0.1,
            model=model_name,
        )
        synthesis = retry.synthesis.strip()
        if _looks_generic_synthesis(synthesis) or not _has_synthesis_details(synthesis):
            logger.warning("Compose final: synthesis still generic/thin; using deterministic fallback.")
            synthesis = _fallback_synthesis(state, language)
    synthesis = _ensure_synthesis_has_details(synthesis, state, language)
    logger.info("Compose final: final synthesis ready (len=%d).", len(synthesis))

    return {**state, "synthesis": synthesis}
