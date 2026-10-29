"""Verification (graph node 7): code checks, then the exact vote list (Q12, F11).

Every verdict a reader sees is written here, from the tally: the writer's
schema has no verdict, so its prose cannot put a different one in a heading.
Every citation names a source the forecast read, cited by number; the URL
comes from the source list. A defect the writer can fix goes back to it once
with the defect named (`find_defect`); anything else is a hard error, never
a repaired answer.

The vote list opens with lines counted here, never by a model (user
decisions 2026-09-30 and 2026-10-01): how many members voted, how many kept a
round-1 vote, how much research the verdicts stand on, how many passages of it
the council read, and a time box or failed searches that cut research short.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from langgraph.runtime import Runtime

from agents.deep_forecaster.citations import (
    SOURCE_LINK,
    SOURCE_MENTION,
    SOURCE_NUMBER,
    link_sources,
    links_in,
    quoted_sources,
)
from agents.deep_forecaster.config import COUNCIL
from agents.deep_forecaster.consts.editorial import WORDS, Words
from agents.deep_forecaster.consts.forecasters import FORECASTER_SOURCES, VIDEO_DOMAINS
from agents.deep_forecaster.consts.progress import VERIFY_LABEL
from agents.deep_forecaster.models import Analysis, Ballot, Claim, Language
from agents.deep_forecaster.render import render_numbers, render_reason
from agents.deep_forecaster.state import (
    ClaimTally,
    ForecastRun,
    ForecastState,
    ResearchOutcome,
)
from models import Source
from services.web_search import allowed_domain
from shared.config import MAX_ANSWER_CHARS
from shared.errors import LLMInvocationError

logger = logging.getLogger(__name__)


async def verify(state: ForecastState, runtime: Runtime[ForecastRun]) -> dict[str, Any]:
    """Check the analysis; send it back once with its defect, or return the answer."""
    runtime.context.enter(VERIFY_LABEL, runtime.stream_writer)
    defect = find_defect(state["analysis"], state["tally"], state["sources"])
    if defect is not None:
        if "feedback" in state:
            # The one rewrite is spent (brainstorm 2026Oct16 Q6).
            raise LLMInvocationError(defect)
        logger.warning("verify: sending the analysis back once: %s", defect)
        return {"feedback": defect}
    return {"answer": checked_answer(state)}


def _host(url: str) -> str:
    """Return `url`'s host, lowercased, without `www.`."""
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _site(url: str) -> str:
    """Return the allow-listed site `url` belongs to, or its host (recorded eval URLs)."""
    return allowed_domain(url, FORECASTER_SOURCES) or _host(url)


def _deadline(deadline: date, words: Words) -> str:
    """Return a date in full words in the answer's language, e.g. "31 grudnia 2027"."""
    return f"{deadline.day} {words.months[deadline.month - 1]} {deadline.year}"


def _counted(number: int, noun: str) -> str:
    """Return e.g. "1 source" or "8 sources"."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def find_defect(
    analysis: Analysis, tally: Sequence[ClaimTally], sources: Sequence[Source]
) -> str | None:
    """Return the analysis's first defect a rewrite can fix, or None.

    Checks 1-4 of the brainstorm (2026Oct16): every claim discussed once, no
    empty section, citations by number only and all linkable, every number a
    source read. Each text names the defect for the writer's rewrite and
    quotes no model text (section numbers are validated integers). Check 5,
    the answer's length, is not here: a rewrite shortens only the analysis,
    never the vote list, so it stays a hard error in `checked_answer`.
    """
    written = sorted(section.claim for section in analysis.claims)
    expected = [counted.claim for counted in tally]
    if written != expected:
        return (
            "The analysis did not discuss every claim exactly once: it needs one "
            f"section for each of claims {render_numbers(expected)} and wrote sections "
            f"for {render_numbers(written) or 'none'}."
        )
    sections = sorted(analysis.claims, key=lambda section: section.claim)
    if not analysis.overview.strip():
        return "The analysis left a section empty: the overview."
    empty = [s.claim for s in sections if not s.discussion.strip()]
    if empty:
        return f"The analysis left a section empty: claim {render_numbers(empty)}."
    text = "\n".join([analysis.overview, *(s.discussion for s in sections)])
    written_urls = links_in(text)
    if written_urls:
        logger.error("verify: the analysis wrote %d URL(s)", len(written_urls))
        return (
            "The analysis wrote a URL; it must cite sources only as [anchor](source:N)."
        )
    cited = SOURCE_LINK.findall(text)
    if len(SOURCE_MENTION.findall(text)) > len(cited):
        return (
            "The analysis wrote a citation the answer cannot link; write each one "
            "exactly as [anchor](source:N)."
        )
    if not cited:
        return "The analysis cited none of the sources it read."
    bad = [
        n
        for n in cited
        if not (SOURCE_NUMBER.fullmatch(n) and 1 <= int(n) <= len(sources))
    ]
    if bad:
        # The count, never the text: what follows `source:` is model-written.
        return (
            f"The analysis cites {_counted(len(bad), 'source number')} outside "
            f"1 to {len(sources)}, the sources the forecast read; cite whole "
            "source numbers such as (source:3)."
        )
    return None


def evidence_line(
    sources: Sequence[Source],
    research: ResearchOutcome,
    claims: Sequence[Claim],
    language: Language,
) -> str:
    """Return the vote list's evidence line: what the verdicts stand on.

    It says how many passages the council voted on, because members read
    those, not every source read (user decision 2026-10-01).
    """
    sites = {_site(source.url) for source in sources}
    videos = sum(1 for source in sources if _site(source.url) in VIDEO_DOMAINS)
    passages = sum(len(claim.evidence) for claim in claims)
    if language == "pl":
        line = f"Dowody: przeczytane źródła: {len(sources)}, witryny: {len(sites)}"
        if videos:
            line += f", w tym notatki Gemini do wideo: {videos}"
        line += (
            f". Rada głosowała na podstawie cytowanych fragmentów: {passages}, "
            f"pochodzących z liczby źródeł: {len(quoted_sources(claims))}."
        )
        if research.timed_out:
            line += " Badanie zatrzymał limit czasu."
        if research.failed_searches:
            line += (
                f" Nieudane wyszukiwania: {research.failed_searches} "
                f"z {research.searches}."
            )
        return line
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


def checked_answer(state: ForecastState) -> str:
    """Return the defect-free analysis followed by the vote list, or raise if it is too long.

    `verify` has already run `find_defect` on this analysis.
    """
    analysis, tally, sources = state["analysis"], state["tally"], state["sources"]
    words = WORDS[analysis.language]
    sections = sorted(analysis.claims, key=lambda section: section.claim)
    parts = [link_sources(analysis.overview.strip(), sources)]
    for section, counted, claim in zip(sections, tally, state["claims"], strict=True):
        parts.append(
            f"## {words.claim} {counted.claim}: {claim.statement}\n"
            f"{words.by_deadline} {_deadline(claim.deadline, words)}. "
            f"{words.council_verdict}: **{words.verdicts[counted.verdict]}**"
            f"\n\n{link_sources(section.discussion.strip(), sources)}"
        )
    parts.append(
        _vote_list(
            tally,
            state["final_ballots"],
            set(state["ballots_round_2"]),
            sources,
            state["research"],
            state["claims"],
            analysis.language,
        )
    )
    answer = "\n\n".join(parts)
    # A vote list the delivery layer's clip cuts off is a design failure
    # (review thread, #143): the reader must see every verdict. A rewrite can
    # only shorten the analysis, never the vote list, so this is not a defect.
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
    language: Language,
) -> str:
    """Render every counted vote in full words, with links from source numbers."""
    words = WORDS[language]
    polish = language == "pl"
    voting = len(ballots)
    unavailable = len(COUNCIL) - voting
    carried = len(set(ballots) - revised)
    if polish:
        voters = f"Głosowało członków: {voting} z {len(COUNCIL)}" + (
            f" (niedostępnych: {unavailable})." if unavailable else "."
        )
    else:
        voters = f"Members voting: {voting} of {len(COUNCIL)}" + (
            f" ({unavailable} unavailable)." if unavailable else "."
        )
    lines = [words.vote_list_heading, "", voters]
    # One paragraph each: Markdown would join adjacent lines into one.
    if carried:
        lines += [
            "",
            (
                f"Runda 2: członkowie, którzy zostali przy głosie z rundy 1, "
                f"bo nie odpowiedzieli: {carried} z {voting}."
                if polish
                else f"Round 2: {carried} of {voting} kept their round-1 vote because "
                "they did not answer."
            ),
        ]
    lines += ["", evidence_line(sources, research, claims, language)]
    for counted in tally:
        lines += [
            "",
            f"### {words.claim} {counted.claim}: {words.verdicts[counted.verdict]}",
            (
                f"Za: {counted.votes_for}, przeciw: {counted.against}, "
                f"niepewnych: {counted.unsure} (głosowało {voting})."
                if polish
                else f"{counted.votes_for} of {voting} voted for, {counted.against} "
                f"against, {counted.unsure} unsure."
            ),
            "",
        ]
        for member, ballot in sorted(ballots.items()):
            vote = next(v for v in ballot.votes if v.claim == counted.claim)
            cited = ", ".join(
                f"[{words.source} {n}]({sources[n - 1].url})" for n in vote.evidence
            )
            # Not `carried`: that name holds the count above, and mypy --strict
            # refuses rebinding an int to a str (correctness review).
            mark = "" if member in revised else words.carried_vote
            lines.append(
                f"- {words.member} {member}{mark}: {words.stances[vote.stance]} — "
                f"{render_reason(vote.reason)}" + (f" ({cited})" if cited else "")
            )
    return "\n".join(lines)
