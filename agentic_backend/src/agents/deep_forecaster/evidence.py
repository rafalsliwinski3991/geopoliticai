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
from agents.deep_forecaster.models import Ballot, Claim
from models import Source

# Every link the chat UI can make clickable in model-written text: an http(s)
# URL in any Markdown form (inline, `<autolink>`, bare, reference definition)
# and a GFM `www.` autolink. `frontend/chat/src/lib/markdown.ts` renders an
# `<a>` only for `^https?://` hrefs, so `//host` and `ftp:` stay plain text.
# Brackets, parentheses and angle brackets end a match, so an inline link's
# `)` is not part of its URL; a URL that itself contains `)` is cut short
# (the known limit of `evals/helpers/judge.py`'s link pattern).
LINK = re.compile(
    r"https?://[^\s<>()\[\]]+|(?<![\w@.])www\.[^\s<>()\[\]]+", re.IGNORECASE
)
# Sentence punctuation after a bare URL is not part of it (as GFM treats it).
TRAILING_PUNCTUATION = ".,;:!?'\""
# A member's reason is shown to other members and printed in the answer
# (Q12). Evidence goes through source numbers, which code turns into links to
# sources read; a link a model wrote into a reason never reaches anyone.
REMOVED_LINK = "(link removed)"
# The writer cites a source by its number, `[anchor](source:3)`; code puts in
# the URL the forecast read (brainstorm 2026Oct16 Q3), as `verify._vote_list`
# already does. Only this exact form is linked. Anything between `source:` and
# `)` is captured, so `(source:3.4)` or `(source:x)` reaches the number check.
SOURCE_LINK = re.compile(r"\]\(source:([^)\s]*)\)", re.IGNORECASE)
# Every place the prose names a source by number, in citation shape only: not
# part of a longer word ("resource:", "open-source:") and a number of one to
# three digits not swallowed by a longer run, so "(Source: 2024 yearbook)"
# stays prose. A count above the `SOURCE_LINK` count means a citation the
# answer cannot link (a title, a space, angle brackets, a bare `(source:3)`),
# which would ship as dead text.
SOURCE_MENTION = re.compile(
    r"(?<![\w-])source:\s*<?\s*[0-9]{1,3}(?![0-9])", re.IGNORECASE
)
# A valid source number: one to three ASCII digits. `str.isdigit` also accepts
# "²", which `int` rejects (framework review).
SOURCE_NUMBER = re.compile(r"[0-9]{1,3}")


def render_reason(reason: str) -> str:
    """Return a reason on one line, with any link it carries removed."""
    return " ".join(LINK.sub(REMOVED_LINK, reason).split())


def links_in(text: str) -> list[str]:
    """Return every clickable link in model-written Markdown, as written."""
    return [url.rstrip(TRAILING_PUNCTUATION) for url in LINK.findall(text)]


def link_sources(text: str, sources: Sequence[Source]) -> str:
    """Return `text` with each `](source:N)` pointing at source N's URL.

    Call only after `verify` has checked every N is a source read.
    """
    return SOURCE_LINK.sub(
        lambda match: f"]({sources[int(match.group(1)) - 1].url})", text
    )


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


def quoted_sources(claims: Sequence[Claim]) -> frozenset[int]:
    """Return the numbers of the sources the claims' evidence refs quote."""
    return common_quoted(claims)


def quoted_sources_by_claim(
    claims: Sequence[Claim],
) -> dict[int, frozenset[int]]:
    """Return, per claim (counting from 1), the sources its evidence refs quote.

    The council's votes check against this per-claim map, not the union:
    a vote on claim 1 may cite only what claim 1 quotes (review thread, #142).
    """
    return {
        number: frozenset(ref.source for ref in claim.evidence)
        for number, claim in enumerate(claims, start=1)
    }


def common_quoted(claims: Sequence[Claim]) -> frozenset[int]:
    """Return the union of every claim's quoted sources."""
    return frozenset(ref.source for claim in claims for ref in claim.evidence)


def render_passages(claims: Sequence[Claim], sources: Sequence[Source]) -> str:
    """Return each claim with its passages copied from the sources, then the sources quoted.

    The text is code's copy of the paragraph each `EvidenceRef` names, never a
    model's: `draft_claims.checked_claims` has already checked every number.
    Each claim's block ends with a `Cite only:` line naming the sources its
    passages quote — the rule `council.validate_ballot` enforces, stated where
    the members read it.
    """
    blocks = []
    for number, claim in enumerate(claims, start=1):
        lines = [
            f"Claim {number}: {claim.statement} "
            f"(deadline: {render_deadline(claim.deadline)})"
        ]
        for ref in claim.evidence:
            text = paragraphs(sources[ref.source - 1].text)[ref.paragraph - 1]
            lines.append(f'- Source {ref.source}: "{text}"')
        allowed = sorted({ref.source for ref in claim.evidence})
        # The rule `council.validate_ballot` enforces, stated where members
        # read the passages (plan review: the prompt used to promise every
        # quoted source).
        lines.append(f"Cite only: {', '.join(f'Source {n}' for n in allowed)}")
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
