"""How model-written text links to sources: URLs, `source:N` citations, paragraphs and quoted passages."""

from __future__ import annotations

import re
from collections.abc import Sequence

from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.models import Claim
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


def paragraphs(text: str) -> list[str]:
    """Return a source's paragraphs: its non-blank lines, each on one line.

    trafilatura puts each extracted paragraph, heading and list item on its
    own line (`services.page_reader._extract_page_sync`), and Gemini's notes are one point per
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
