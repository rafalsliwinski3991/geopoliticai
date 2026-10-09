"""Verification (graph node 7): code checks, then the exact vote list (Q12, F11).

Every verdict a reader sees is written here, from the tally: the writer's
schema has no verdict, so its prose cannot put a different one in a heading.
Every link must be a source the forecast read (brainstorm §3), compared after
normalising the URL. Any failure is a hard error, never a repaired answer.

The vote list opens with lines counted here, never by a model (user
decisions 2026-09-30 and 2026-10-01): how many members voted, how many kept a
round-1 vote, how much research the verdicts stand on, how many passages of it
the council read, and a time box or failed searches that cut research short.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from langgraph.runtime import Runtime

from agents.deep_forecaster.config import COUNCIL
from agents.deep_forecaster.consts.editorial import CARRIED_VOTE, VOTE_LIST_HEADING
from agents.deep_forecaster.consts.forecasters import FORECASTER_SOURCES, VIDEO_DOMAINS
from agents.deep_forecaster.consts.progress import VERIFY_LABEL
from agents.deep_forecaster.council import final_ballots
from agents.deep_forecaster.evidence import (
    links_in,
    quoted_sources,
    render_deadline,
    render_reason,
)
from agents.deep_forecaster.models import Analysis, Ballot, Claim
from agents.deep_forecaster.state import (
    ClaimTally,
    ForecastRun,
    ForecastState,
    ResearchOutcome,
)
from config import MAX_ANSWER_CHARS
from models import LLMInvocationError, Source
from search import allowed_domain


async def verify(state: ForecastState, runtime: Runtime[ForecastRun]) -> dict[str, Any]:
    """Check the analysis and return the answer the reader sees."""
    runtime.context.enter(VERIFY_LABEL, runtime.stream_writer)
    revised = state["ballots_round_2"]
    return {
        "answer": checked_answer(
            state["analysis"],
            state["claims"],
            state["tally"],
            final_ballots(state["ballots_round_1"], revised),
            set(revised),
            state["sources"],
            state["research"],
        )
    }


def _host(url: str) -> str:
    """Return `url`'s host, lowercased, without `www.`."""
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _normalized(url: str) -> str:
    """Return `url` without the differences a writer introduces when copying it.

    The scheme is kept (review thread, #143): `http://host/path` cannot
    validate against a source read at `https://host/path`, so a model-written
    citation can never inside-import readers to an insecure URL the forecast
    did not read. Host case, `www.`, a trailing slash and the fragment are
    normalized; a scheme-less `www.` link is read as https.
    """
    url = url if "://" in url else f"https://{url}"
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme}://{_host(url)}{path}{query}"


def _site(url: str) -> str:
    """Return the allow-listed site `url` belongs to, or its host (recorded eval URLs)."""
    return allowed_domain(url, FORECASTER_SOURCES) or _host(url)


def _counted(number: int, noun: str) -> str:
    """Return e.g. "1 source" or "8 sources"."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def evidence_line(
    sources: Sequence[Source], research: ResearchOutcome, claims: Sequence[Claim]
) -> str:
    """Return the vote list's evidence line: what the verdicts stand on.

    It says how many passages the council voted on, because members read
    those, not every source read (user decision 2026-10-01).
    """
    sites = {_site(source.url) for source in sources}
    videos = sum(1 for source in sources if _site(source.url) in VIDEO_DOMAINS)
    passages = sum(len(claim.evidence) for claim in claims)
    line = (
        f"Evidence: {_counted(len(sources), 'source')} read from "
        f"{_counted(len(sites), 'site')}"
    )
    if videos:
        line += f", {videos} of them Gemini's notes on a video"
    line += (
        f". The council voted on {_counted(passages, 'passage')} quoted from "
        f"{len(quoted_sources(claims))} of them."
    )
    if research.timed_out:
        line += " Research stopped at its time limit."
    if research.failed_searches:
        line += f" {research.failed_searches} of {research.searches} searches failed."
    return line


def checked_answer(
    analysis: Analysis,
    claims: Sequence[Claim],
    tally: Sequence[ClaimTally],
    ballots: Mapping[int, Ballot],
    revised: set[int],
    sources: Sequence[Source],
    research: ResearchOutcome,
) -> str:
    """Return the analysis followed by the vote list, or raise if it breaks a rule."""
    sections = sorted(analysis.claims, key=lambda section: section.claim)
    if [section.claim for section in sections] != [t.claim for t in tally]:
        raise LLMInvocationError(
            "The analysis did not discuss every claim exactly once."
        )
    prose = [analysis.overview, *(section.discussion for section in sections)]
    if not all(text.strip() for text in prose):
        raise LLMInvocationError("The analysis left a section empty.")
    # Every clickable form counts, not only inline links (correctness review):
    # injected page text could make the writer emit a bare or reference link.
    linked = {_normalized(url) for url in links_in("\n".join(prose))}
    if not linked:
        raise LLMInvocationError("The analysis cited none of the sources it read.")
    if linked - {_normalized(source.url) for source in sources}:
        raise LLMInvocationError(
            "The analysis links to a page the forecast never read."
        )
    parts = [analysis.overview.strip()]
    for section, counted, claim in zip(sections, tally, claims, strict=True):
        parts.append(
            f"## Claim {counted.claim}: {claim.statement}\n"
            f"By {render_deadline(claim.deadline)}. Council verdict: **{counted.verdict}**"
            f"\n\n{section.discussion.strip()}"
        )
    parts.append(_vote_list(tally, ballots, revised, sources, research, claims))
    answer = "\n\n".join(parts)
    # A vote list the delivery layer's clip cuts off is a design failure
    # (review thread, #143): the reader must see every verdict.
    if len(answer) > MAX_ANSWER_CHARS:
        raise LLMInvocationError(
            f"The answer is {len(answer)} characters; it exceeds "
            f"the delivery cap ({MAX_ANSWER_CHARS}) and its vote list would be cut."
        )
    return answer


def _vote_list(
    tally: Sequence[ClaimTally],
    ballots: Mapping[int, Ballot],
    revised: set[int],
    sources: Sequence[Source],
    research: ResearchOutcome,
    claims: Sequence[Claim],
) -> str:
    """Render every counted vote in full words, with links from source numbers."""
    voting = len(ballots)
    unavailable = len(COUNCIL) - voting
    carried = len(set(ballots) - revised)
    lines = [
        VOTE_LIST_HEADING,
        "",
        f"Members voting: {voting} of {len(COUNCIL)}"
        + (f" ({unavailable} unavailable)." if unavailable else "."),
    ]
    # One paragraph each: Markdown would join adjacent lines into one.
    if carried:
        lines += [
            "",
            f"Round 2: {carried} of {voting} kept their round-1 vote because "
            "they did not answer.",
        ]
    lines += ["", evidence_line(sources, research, claims)]
    for counted in tally:
        lines += [
            "",
            f"### Claim {counted.claim}: {counted.verdict}",
            f"{counted.votes_for} of {voting} voted for, {counted.against} against, "
            f"{counted.unsure} unsure.",
            "",
        ]
        for member, ballot in sorted(ballots.items()):
            vote = next(v for v in ballot.votes if v.claim == counted.claim)
            cited = ", ".join(
                f"[Source {n}]({sources[n - 1].url})" for n in vote.evidence
            )
            # Not `carried`: that name holds the count above, and mypy --strict
            # refuses rebinding an int to a str (correctness review).
            mark = "" if member in revised else CARRIED_VOTE
            lines.append(
                f"- Member {member}{mark}: {vote.stance} — {render_reason(vote.reason)}"
                + (f" ({cited})" if cited else "")
            )
    return "\n".join(lines)
