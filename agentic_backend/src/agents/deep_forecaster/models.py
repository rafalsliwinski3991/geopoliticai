"""What the drafter drafts and what the council votes: the typed messages.

These are the pydantic models a model call fills (`draft_claims`' structured
output) or the answer carries. The run-level records live in `state.py`
(review thread, #142): `EvidenceRef`, `Claim`, `DraftedClaims`, `Vote` and
`Ballot` here; `ForecastState`, `ForecastRun`, `ResearchRun`, `ResearchOutcome`
and `ClaimTally` there.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Stance = Literal["for", "against", "unsure"]
Verdict = Literal["ACCEPTED", "REJECTED", "UNRESOLVED"]


class EvidenceRef(BaseModel):
    """One numbered paragraph of one numbered source, as evidence on a claim.

    The drafter only points (user decision 2026-10-01): `evidence.render_passages`
    copies the paragraph's text from the source, so no council member ever
    reads model-written evidence.
    """

    source: int = Field(description="The source's number, as in 'SOURCE 3'.")
    paragraph: int = Field(
        description="The paragraph's number within that source: 12 for [3.12]."
    )


class Claim(BaseModel):
    """One checkable statement about the future (brainstorm Q13b, Q27)."""

    statement: str = Field(
        description=(
            "One concrete outcome, stated so that on the deadline anyone can "
            "tell whether it came true. No 'might', 'could' or 'likely'."
        )
    )
    deadline: date = Field(
        description="The date by which the statement is true or false."
    )
    evidence: list[EvidenceRef] = Field(
        description=(
            "One to six paragraphs that bear most on this claim, from both "
            "sides where the sources disagree. The council reads only these."
        )
    )


class DraftedClaims(BaseModel):
    """`draft_claims`' structured output; `nodes.draft_claims.checked_claims` validates it."""

    claims: list[Claim] = Field(description="Two to four distinct claims.")


class Vote(BaseModel):
    """One member's vote on one claim (Q7)."""

    claim: int = Field(description="The claim's number, as in 'Claim 2'.")
    stance: Stance = Field(
        description=(
            "'for': more likely than not to be true by its deadline; 'against': "
            "less likely; 'unsure': the sources are too thin to lean either way."
        )
    )
    reason: str = Field(description="One to three sentences, with no links or URLs.")
    evidence: list[int] = Field(
        description=(
            "The numbers of the sources whose paragraphs the reason rests on, at "
            "most 5. Required for 'for' and 'against'; may be empty for 'unsure'."
        )
    )

    @model_validator(mode="before")
    @classmethod
    def _read_unsure_without_evidence_as_none(cls, data: Any) -> Any:
        """Read an `unsure` vote whose `evidence` is missing or null as citing none.

        The Anthropic seat left the empty list out in 3 of 4 round-1s on the
        2026-10-14 roster, and pydantic refused the whole ballot. Only that
        case is read as the empty list it means: the schema still requires
        `evidence` for every vote, so no seat is invited to drop it on 'for'
        or 'against' (plan review, brainstorm 2026Oct19 Q1).
        """
        if (
            isinstance(data, dict)
            and data.get("stance") == "unsure"
            and data.get("evidence") is None
        ):
            return {**data, "evidence": []}
        return data


class ClaimDiscussion(BaseModel):
    """The writer's section on one claim (Q12)."""

    claim: int = Field(description="The claim's number.")
    discussion: str = Field(
        description=(
            "Markdown: the strongest reasons members gave on each side and where "
            "they disagreed, citing sources by number as [anchor](source:N)."
        )
    )


class Analysis(BaseModel):
    """`write_analysis`' structured output; `nodes.verify` checks it and renders it."""

    overview: str = Field(
        description=(
            "Markdown: the forecast in two to four paragraphs, citing sources "
            "by number as [anchor](source:N)."
        )
    )
    claims: list[ClaimDiscussion] = Field(
        description="One entry per claim, in claim order."
    )


class Ballot(BaseModel):
    """One member's votes in one round; `council.validate_ballot` decides if it counts."""

    votes: list[Vote] = Field(description="Exactly one vote per claim.")
