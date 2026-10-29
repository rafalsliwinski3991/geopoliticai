"""The forecaster's fixed editorial strings the answer node prints.

Per repository layout, editorial data lives under `consts/` (review thread,
#143); `nodes.verify` imports them. Each string exists in English and Polish:
the reader gets the language the question was asked in (`Analysis.language`).
Polish counts are written as `label: number`, which needs no case or plural
form.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.deep_forecaster.models import Language, Stance, Verdict


@dataclass(frozen=True)
class Words:
    """Every word of the answer that code, not the writer, prints."""

    vote_list_heading: str
    carried_vote: str
    claim: str
    by_deadline: str
    council_verdict: str
    verdicts: dict[Verdict, str]
    stances: dict[Stance, str]
    source: str
    member: str
    months: tuple[str, ...]


WORDS: dict[Language, Words] = {
    "en": Words(
        vote_list_heading="## How the council voted",
        carried_vote=" (round-1 vote)",
        claim="Claim",
        by_deadline="By",
        council_verdict="Council verdict",
        verdicts={
            "ACCEPTED": "ACCEPTED",
            "REJECTED": "REJECTED",
            "UNRESOLVED": "UNRESOLVED",
        },
        stances={"for": "for", "against": "against", "unsure": "unsure"},
        source="Source",
        member="Member",
        months=(
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
    ),
    "pl": Words(
        vote_list_heading="## Jak głosowała rada",
        carried_vote=" (głos z rundy 1)",
        claim="Twierdzenie",
        by_deadline="Do",
        council_verdict="Werdykt rady",
        verdicts={
            "ACCEPTED": "PRZYJĘTE",
            "REJECTED": "ODRZUCONE",
            "UNRESOLVED": "NIEROZSTRZYGNIĘTE",
        },
        stances={"for": "za", "against": "przeciw", "unsure": "niepewny"},
        source="Źródło",
        member="Członek",
        months=(
            "stycznia",
            "lutego",
            "marca",
            "kwietnia",
            "maja",
            "czerwca",
            "lipca",
            "sierpnia",
            "września",
            "października",
            "listopada",
            "grudnia",
        ),
    ),
}
