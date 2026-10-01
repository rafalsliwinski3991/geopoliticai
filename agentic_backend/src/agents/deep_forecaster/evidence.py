"""How sources, paragraphs, claims and ballots are numbered and written out.

One module, so every step numbers them the same way: sources and claims count
from 1 in state order, a paragraph counts from 1 within its source, and a
member's number is its seat's position in `config.COUNCIL`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.state import Ballot, Claim
from models import Source

# Every link the chat UI can make clickable in model-written text: an http(s)
# URL in any Markdown form (inline, `<autolink>`, bare, reference definition)
# and a GFM `www.` autolink. `frontend/chat/src/lib/markdown.ts` renders an
# `<a>` only for `^https?://` hrefs, so `//host` and `ftp:` stay plain text.
# Brackets, parentheses and angle brackets end a match, so an inline link's
# `)` is not part of its URL; a URL that itself contains `)` is cut short
# (the known limit of `evals/helpers/judge.py`'s link pattern).
LINK = re.compile(r"https?://[^\s<>()\[\]]+|www\.[^\s<>()\[\]]+", re.IGNORECASE)
# Sentence punctuation after a bare URL is not part of it (as GFM treats it).
TRAILING_PUNCTUATION = ".,;:!?'\""
# A member's reason is shown to other members and printed in the answer
# (Q12). Evidence goes through source numbers, which code turns into links to
# sources read; a link a model wrote into a reason never reaches anyone.
REMOVED_LINK = "(link removed)"


def render_reason(reason: str) -> str:
    """Return a reason on one line, with any link it carries removed."""
    return " ".join(LINK.sub(REMOVED_LINK, reason).split())


def links_in(text: str) -> list[str]:
    """Return every clickable link in model-written Markdown, as written."""
    return [url.rstrip(TRAILING_PUNCTUATION) for url in LINK.findall(text)]


def render_deadline(deadline: date) -> str:
    """Return a date in full words, e.g. "31 December 2027"."""
    return f"{deadline.day} {deadline:%B %Y}"


def render_claims(claims: Sequence[Claim]) -> str:
    """Return one `Claim n: statement (deadline: ...)` line per claim."""
    return "\n".join(
        f"Claim {number}: {claim.statement} (deadline: {render_deadline(claim.deadline)})"
        for number, claim in enumerate(claims, start=1)
    )


def paragraphs(text: str) -> list[str]:
    """Return a source's paragraphs: its non-blank lines, each on one line.

    trafilatura puts each extracted paragraph, heading and list item on its
    own line (`search._extract_sync`), and Gemini's notes are one point per
    line, so a line is the unit the drafter can point at. A line longer than
    `max_passage_chars` is split at the last space before the limit, so a
    page extracted as one block still offers every part of itself and no
    quoted passage is ever cut (correctness review).
    """
    found: list[str] = []
    for line in text.splitlines():
        rest = " ".join(line.split())
        while len(rest) > LIMITS.max_passage_chars:
            cut = rest.rfind(" ", 0, LIMITS.max_passage_chars + 1)
            cut = cut if cut > 0 else LIMITS.max_passage_chars
            found.append(rest[:cut])
            rest = rest[cut:].lstrip()
        if rest:
            found.append(rest)
    return found


def render_sources(sources: Sequence[Source]) -> str:
    """Return every source in full, numbered, with its byline, URL and numbered paragraphs."""
    return "\n\n".join(
        f"--- SOURCE {number} ---\nTitle: {source.title}\n"
        f"Byline: {source.author or 'none'}\nURL: {source.url}\n\n"
        + "\n".join(
            f"[{number}.{index}] {paragraph}"
            for index, paragraph in enumerate(paragraphs(source.text), start=1)
        )
        for number, source in enumerate(sources, start=1)
    )


def quoted_sources(claims: Sequence[Claim]) -> frozenset[int]:
    """Return the numbers of the sources the claims' passages are quoted from."""
    return frozenset(ref.source for claim in claims for ref in claim.passages)


def render_passages(claims: Sequence[Claim], sources: Sequence[Source]) -> str:
    """Return each claim with its passages copied from the sources, then the sources quoted.

    The text is code's copy of the paragraph each `PassageRef` names, never a
    model's: `draft_claims.checked_claims` has already checked every number.
    """
    blocks = []
    for number, claim in enumerate(claims, start=1):
        lines = [
            f"Claim {number}: {claim.statement} "
            f"(deadline: {render_deadline(claim.deadline)})"
        ]
        for ref in claim.passages:
            text = paragraphs(sources[ref.source - 1].text)[ref.paragraph - 1]
            lines.append(f'- Source {ref.source}: "{text}"')
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
