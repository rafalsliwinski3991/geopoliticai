"""How sources, paragraphs, claims and ballots are numbered and written out.

One module, so every step numbers them the same way: sources and claims count
from 1 in state order, a paragraph counts from 1 within its source, and a
member's number is its seat's position in `config.COUNCIL`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from agents.deep_forecaster.citations import (
    LINK,
    REMOVED_LINK,
    paragraphs,
    quoted_sources,
    quoted_sources_by_claim,
)
from agents.deep_forecaster.models import Ballot, Claim
from models import Source


def render_reason(reason: str) -> str:
    """Return a reason on one line, with any link it carries removed."""
    return " ".join(LINK.sub(REMOVED_LINK, reason).split())


def render_deadline(deadline: date) -> str:
    """Return a date in full words, e.g. "31 December 2027"."""
    return f"{deadline.day} {deadline:%B %Y}"


def render_numbers(numbers: Sequence[int]) -> str:
    """Return numbers as a reader reads them: "3", "3 and 5", "3, 5 and 9"."""
    words = [str(number) for number in numbers]
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"


def render_claims(claims: Sequence[Claim]) -> str:
    """Return one `Claim n: statement (deadline: ...)` line per claim."""
    return "\n".join(
        f"Claim {number}: {claim.statement} (deadline: {render_deadline(claim.deadline)})"
        for number, claim in enumerate(claims, start=1)
    )


def render_sources(sources: Sequence[Source], *, urls: bool = True) -> str:
    """Return every source in full, numbered, with its byline, URL and numbered paragraphs.

    The writer's brief passes `urls=False`: a writer that never sees a URL
    cannot copy one wrong (brainstorm 2026Oct16, trace 8a80df9c). With
    `urls=False` a URL in a title, byline or the source's own text is
    neutralised the way `render_reason` does (`LINK.sub(REMOVED_LINK, ...)`),
    so the writer sees no URL anywhere in its brief and `find_defect` cannot
    call its prose a defect.
    """

    def line(text: str) -> str:
        """Neutralise any link in model- or page-written text for the brief."""
        return LINK.sub(REMOVED_LINK, text) if not urls else text

    return "\n\n".join(
        f"--- SOURCE {number} ---\nTitle: {line(source.title)}\n"
        f"Byline: {line(source.author or 'none')}\n"
        + (f"URL: {source.url}\n" if urls else "")
        + "\n"
        + "\n".join(
            f"[{number}.{index}] {line(paragraph)}"
            for index, paragraph in enumerate(paragraphs(source.text), start=1)
        )
        for number, source in enumerate(sources, start=1)
    )


def render_passages(claims: Sequence[Claim], sources: Sequence[Source]) -> str:
    """Return each claim with its passages copied from the sources, then the sources quoted.

    The text is code's copy of the paragraph each `EvidenceRef` names, never a
    model's: `draft_claims.checked_claims` has already checked every number.
    Each claim's block ends with a `Cite only:` line naming the sources its
    passages quote — the rule `council.validate_ballot` enforces, stated where
    the members read it.
    """
    # One map for both the `Cite only:` line and the vote check, so the rule
    # the members read cannot drift from the rule `council.validate_ballot`
    # enforces (review thread; plan review: the prompt used to promise every
    # quoted source).
    quoted = quoted_sources_by_claim(claims)
    blocks = []
    for number, claim in enumerate(claims, start=1):
        lines = [
            f"Claim {number}: {claim.statement} "
            f"(deadline: {render_deadline(claim.deadline)})"
        ]
        for ref in claim.evidence:
            text = paragraphs(sources[ref.source - 1].text)[ref.paragraph - 1]
            lines.append(f'- Source {ref.source}: "{text}"')
        lines.append(
            f"Cite only: {', '.join(f'Source {n}' for n in sorted(quoted[number]))}"
        )
        blocks.append("\n".join(lines))
    index = "\n".join(
        f"Source {n}: {sources[n - 1].title} (byline: "
        f"{sources[n - 1].author or 'none'}; {sources[n - 1].url})"
        for n in sorted(quoted_sources(claims))
    )
    return "\n\n".join(blocks) + f"\n\nSources quoted:\n{index}"


def render_ballot(ballot: Ballot) -> str:
    """Return one `Claim n: stance — reason (Sources 3, 5)` line per vote."""
    lines = []
    for vote in sorted(ballot.votes, key=lambda vote: vote.claim):
        cited = (
            f" (Sources {', '.join(str(n) for n in vote.evidence)})"
            if vote.evidence
            else ""
        )
        lines.append(
            f"Claim {vote.claim}: {vote.stance} — {render_reason(vote.reason)}{cited}"
        )
    return "\n".join(lines)
