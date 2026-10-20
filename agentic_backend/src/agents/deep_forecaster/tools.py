"""The scouts' three research tools (brainstorm 2026Sep30 Q15, Q16, Q17c, Q18).

Plain `@tool`s over one `ResearchRun`, independent of who calls them (design
principle 1): deepagents' scouts call them today; a fixed workflow could call
them tomorrow. Each records what it read into the run, and the `research`
node returns those records, never the agent's own text.

- `search_forecaster` searches one forecaster's own domains with up to
  `max_batch` queries at once, with the forecaster's name prefixed to each.
  One query is one Brave request; the searches are spent before any request
  starts, so parallel scouts cannot overshoot the budget; a failed one is a
  message, and at most `max_search_concurrency` run at once.
- `read_sources` reads up to `max_batch` articles a search in this run
  returned, never a video, all at once, and shows each page's own byline and
  at most `max_shown_chars` of its text.
- `ask_video` hands a YouTube URL a search returned to Gemini. Its answer is
  stored as a source titled "Gemini's notes on the video": model-produced, not
  a transcript (Q17c). A refused, rate-limited, failed or timed-out Gemini call
  is a message to the scout (F2); any other exception is a bug and propagates.

The allow-list is enforced twice, as for the deep expert: by
`search_allowlisted` on the narrowed policy and by `fetch_sources`' own check
on `FORECASTER_SOURCES`. A model can never make the service fetch an
arbitrary URL, and Gemini receives only a URL a Brave search returned.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from langchain_core.tools import BaseTool, tool

from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.consts.forecasters import (
    FORECASTER_SOURCES,
    FORECASTERS_BY_ID,
    VIDEO_DOMAINS,
    Forecaster,
)
from agents.deep_forecaster.consts.progress import (
    READ_PROGRESS_LABEL,
    SEARCH_PROGRESS_LABEL,
    VIDEO_PROGRESS_LABEL,
)
from agents.deep_forecaster.prompts import VIDEO_NOT_DISCUSSED
from agents.deep_forecaster.state import ResearchRun
from agents.deep_forecaster.video import VideoUnavailableError, watch_video
from models import Candidate, SearchUnavailableError, Source, SourcePolicy
from search import fetch_sources, search_allowlisted
from tracing import start_span

UNKNOWN_FORECASTER_MESSAGE = "Unknown forecaster id. Use one of: {ids}."
EMPTY_QUERY_MESSAGE = "Every query was empty. Search again with focused queries."
EMPTY_URLS_MESSAGE = "No URLs were given. Pass URLs `search_forecaster` returned."
EMPTY_QUESTION_MESSAGE = (
    "The question was empty. Ask one short question about the topic."
)
NO_SEARCHES_LEFT_MESSAGE = (
    "No searches left. Do not search again; return your findings."
)
NO_RESULTS_MESSAGE = "No results on this forecaster's sites for that query."
QUERY_HEADER = "Query: {query}"
URL_HEADER = "URL: {url}"
NOT_RUN_BATCH_MESSAGE = "Not run (at most {cap} queries per call): {queries}"
NOT_RUN_BUDGET_MESSAGE = "Not run (no searches left): {queries}"
NOT_READ_BATCH_MESSAGE = "Not read (at most {cap} URLs per call): {urls}"
SHOWN_CUT_NOTE = (
    "[First {shown:,} of {total:,} characters shown; the whole page is recorded.]"
)
UNKNOWN_URL_MESSAGE = (
    "Only URLs returned by `search_forecaster` in this research can be read."
)
VIDEO_URL_MESSAGE = "That is a video. Use `ask_video` for YouTube results."
NOT_A_VIDEO_MESSAGE = (
    "`ask_video` takes only YouTube URLs returned by `search_forecaster`."
)
UNREADABLE_MESSAGE = "That page could not be fetched or had no usable article text."
VIDEO_ASKED_AGAIN_MESSAGE = (
    'The notes on this video already answer a different question:\
"{question}". Read them in the sources and cite the video\'s URL.'
)
NO_SOURCES_LEFT_MESSAGE = (
    "No more sources can be read. Do not read more; return your findings."
)
NO_VIDEOS_LEFT_MESSAGE = "No video questions left. Continue with the websites."
VIDEO_UNAVAILABLE_MESSAGE = (
    "Video reading is unavailable right now. Continue with the websites."
)
VIDEO_OFF_TOPIC_MESSAGE = "The video does not discuss this. Try another result."
SEARCH_FAILED_MESSAGE = (
    "That search failed. Try it once more, or continue with what you have."
)
VIDEO_TITLE = "Gemini's notes on the video: {title}"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
# A model-written `site:` names a site outside the forecaster's own domains,
# so the search can only come back empty (Phoenix, 2026-10-14: 6 of 21).
SITE_OPERATOR_RE = re.compile(r"-?\bsite:\S*", re.IGNORECASE)
logger = logging.getLogger(__name__)


def forecaster_policy(forecaster: Forecaster) -> SourcePolicy:
    """Return `FORECASTER_SOURCES` narrowed to one forecaster's domains, one batch."""
    return replace(
        FORECASTER_SOURCES,
        allowed_domains=forecaster.domains,
        batches=(forecaster.domains,),
    )


def _watch_url(url: str) -> str | None:
    """Return one YouTube video's canonical URL, or None for a channel, playlist or short.

    `https://www.youtube.com/watch?v=<id>` is the only form Gemini's docs show,
    and one form per video keeps `…&t=90s` from spending a second video
    (plan v2 review). Only `/watch?v=` URLs are accepted: shorts, `/live/`
    replays and `youtu.be` links (never a search candidate) are a v1 limit.
    """
    parsed = urlparse(url)
    ids = parse_qs(parsed.query).get("v")
    if parsed.path != "/watch" or not ids:
        return None
    # A decoded id may itself carry `&`/`=` (query-string tricks), which would
    # build a different URL, break the one-notes-per-video dedupe and cite a
    # video the page never was (review thread, #140).
    if VIDEO_ID_RE.fullmatch(ids[0]) is None:
        return None
    return f"https://www.youtube.com/watch?v={ids[0]}"


def _shown(source: Source, chars: int | None = None) -> str:
    """Return a recorded source as the tools show it: title, byline, URL, text.

    `chars` cuts the text a batch read shows the scout (`max_shown_chars`);
    the recorded source keeps every character.
    """
    text = source.text
    if chars is not None and len(text) > chars:
        text = f"{text[:chars]}\n{SHOWN_CUT_NOTE.format(shown=chars, total=len(text))}"
    return (
        f"--- SOURCE ---\nTitle: {source.title}\nByline: {source.author or 'none'}\n"
        f"URL: {source.url}\n\n{text}"
    )


def _clean_query(query: str) -> str:
    """Return a model-written query without `site:` operators or extra spaces."""
    return " ".join(SITE_OPERATOR_RE.sub(" ", query).split())


def _render_results(query: str, candidates: list[Candidate] | None) -> str:
    """Return one query's block: its header, then its results, or why there are none."""
    header = QUERY_HEADER.format(query=query)
    if candidates is None:
        return f"{header}\n{SEARCH_FAILED_MESSAGE}"
    if not candidates:
        return f"{header}\n{NO_RESULTS_MESSAGE}"
    return header + "\n" + "\n".join(f"{c.title} | {c.url}" for c in candidates)


def _annotate(url: str, message: str) -> str:
    """Return a message about one URL, headed by the URL it is about."""
    return f"{URL_HEADER.format(url=url)}\n{message}"


def build_tools(run: ResearchRun) -> list[BaseTool]:
    """Return this forecast's `search_forecaster`, `read_sources` and `ask_video`, bound to `run`."""

    @tool
    async def search_forecaster(forecaster: str, queries: list[str]) -> str:
        """Search one forecaster's own websites with one to five focused queries at once.

        `forecaster` is an id from your brief. The queries run together, and
        each spends one search from a shared budget. Returns each query's
        results as `title | url` lines. Read articles with `read_sources`; ask
        about a YouTube result with `ask_video`.
        """
        profile = FORECASTERS_BY_ID.get(forecaster.strip().lower())
        if profile is None:
            return UNKNOWN_FORECASTER_MESSAGE.format(ids=", ".join(FORECASTERS_BY_ID))
        # Model output: a blank query would fail `search.build_batch_query`
        # and surface as a 503 blaming Brave (deep expert, plan v2 row 3), and
        # a repeated one would spend a search on results the scout has.
        asked = [query for query in dict.fromkeys(map(_clean_query, queries)) if query]
        if not asked:
            return EMPTY_QUERY_MESSAGE
        if run.searches >= LIMITS.max_searches:
            return NO_SEARCHES_LEFT_MESSAGE
        batch, over_batch = asked[: LIMITS.max_batch], asked[LIMITS.max_batch :]
        room = LIMITS.max_searches - run.searches
        taken, over_budget = batch[:room], batch[room:]
        # Spent before any request awaits: the tools are `async`, so scouts
        # share one event loop and a parallel scout's batch sees this one's
        # spend (the deep expert's reservation, plan review).
        first = run.searches + 1
        run.searches += len(taken)
        run.forecasters_searched.add(profile.id)
        run.progress(
            SEARCH_PROGRESS_LABEL.format(used=run.searches, cap=LIMITS.max_searches)
        )
        with start_span("search_batch") as span:
            found = await asyncio.gather(
                *(
                    _search_one(profile, query, number)
                    for number, query in enumerate(taken, start=first)
                )
            )
            span.set_attributes(
                {
                    "search.forecaster": profile.id,
                    "search.queries_asked": len(queries),
                    "search.queries_run": len(taken),
                    "search.results": sum(len(c) for c in found if c is not None),
                    "search.empty": sum(1 for c in found if c == []),
                    "search.failed": sum(1 for c in found if c is None),
                    "search.budget_left": LIMITS.max_searches - run.searches,
                }
            )
        blocks = [
            _render_results(query, candidates)
            for query, candidates in zip(taken, found, strict=True)
        ]
        if over_batch:
            blocks.append(
                NOT_RUN_BATCH_MESSAGE.format(
                    cap=LIMITS.max_batch, queries="; ".join(over_batch)
                )
            )
        if over_budget:
            blocks.append(NOT_RUN_BUDGET_MESSAGE.format(queries="; ".join(over_budget)))
        blocks.append(f"Searches left: {LIMITS.max_searches - run.searches}.")
        return "\n\n".join(blocks)

    async def _search_one(
        profile: Forecaster, query: str, number: int
    ) -> list[Candidate] | None:
        """Run one already-spent search; return its candidates, or None when Brave failed.

        One search is one Brave request (one batch), so a single 429 or
        timeout makes `search_allowlisted` raise. That is a message, not an
        error; `nodes.research` still raises the outage when every search
        failed and nothing was read (plan review).
        """
        try:
            async with run.search_gate:
                candidates = await search_allowlisted(
                    f"{profile.search_name} {query}", forecaster_policy(profile)
                )
        except SearchUnavailableError:
            run.failed_searches += 1
            logger.warning("forecast search %d (%s) failed", number, profile.id)
            return None
        for candidate in candidates:
            run.candidates.setdefault(candidate.url, candidate)
            # First finder wins; a search result belongs to the forecaster
            # whose brief produced the query (review thread, #140).
            run.found_by.setdefault(candidate.url, profile.name)
        if not candidates:
            run.empty_searches += 1
        logger.info(
            "forecast search %d (%s): %d candidates",
            number,
            profile.id,
            len(candidates),
        )
        return candidates

    @tool
    async def read_sources(urls: list[str]) -> str:
        """Read one to five articles that `search_forecaster` returned, all at once.

        Shows each page's byline when it has one, and its text up to a limit.
        Cite each page with exactly the URL shown above it.
        """
        asked = list(dict.fromkeys(urls))
        if not asked:
            return EMPTY_URLS_MESSAGE
        batch, over_batch = asked[: LIMITS.max_batch], asked[LIMITS.max_batch :]
        with start_span("read_batch") as span:
            outcomes = await asyncio.gather(*(_read_one(url) for url in batch))
            counts = Counter(outcome for _, outcome in outcomes)
            span.set_attributes(
                {
                    "read.urls_asked": len(urls),
                    "read.pages_read": counts["read"],
                    "read.already_read": counts["already_read"],
                    "read.unreadable": counts["unreadable"],
                    "read.refused": counts["refused"],
                    "read.room_left": LIMITS.max_sources
                    - len(run.sources)
                    - run.reserved,
                }
            )
        blocks = [text for text, _ in outcomes]
        if over_batch:
            blocks.append(
                NOT_READ_BATCH_MESSAGE.format(
                    cap=LIMITS.max_batch, urls="; ".join(over_batch)
                )
            )
        return "\n\n".join(blocks)

    async def _read_one(url: str) -> tuple[str, str]:
        """Read one URL into the run; return what the scout sees, and the outcome.

        The outcome is "read", "already_read", "unreadable" or "refused" (an
        unknown URL, a video, or no room left), for the `read_batch` span.
        """
        candidate = run.candidates.get(url)
        if candidate is None:
            return _annotate(url, UNKNOWN_URL_MESSAGE), "refused"
        if candidate.domain in VIDEO_DOMAINS:
            return _annotate(url, VIDEO_URL_MESSAGE), "refused"
        async with run.lock_for(url):
            source = run.sources.get(url)
            if source is not None:
                return _shown(source, LIMITS.max_shown_chars), "already_read"
            if not run.has_room():
                return _annotate(url, NO_SOURCES_LEFT_MESSAGE), "refused"
            run.reserved += 1
            try:
                fetched = await fetch_sources([candidate], FORECASTER_SOURCES)
            finally:
                run.reserved -= 1
            if not fetched:
                run.unreadable_pages += 1
                return _annotate(url, UNREADABLE_MESSAGE), "unreadable"
            # Recorded under the URL the model asked for, which is the one
            # it will cite, even when a redirect changed `url`.
            source = replace(fetched[0], url=url)
            run.sources[url] = source
            run.progress(READ_PROGRESS_LABEL.format(count=len(run.sources)))
        return _shown(source, LIMITS.max_shown_chars), "read"

    @tool
    async def ask_video(url: str, question: str) -> str:
        """Ask what one YouTube video that `search_forecaster` returned says about a question.

        Gemini watches and listens to the public video and answers in text.
        Its notes are stored as a source under the video's canonical
        `https://www.youtube.com/watch?v=` URL, which the output shows.
        Each new video spends one question from a small shared budget.
        """
        candidate = run.candidates.get(url)
        video = _watch_url(url) if candidate is not None else None
        if candidate is None or candidate.domain not in VIDEO_DOMAINS or video is None:
            # Checked before any budget is spent: Brave's `site:youtube.com`
            # also returns channels, playlists and shorts (framework review).
            return NOT_A_VIDEO_MESSAGE
        question = " ".join(question.split())
        if not question:
            return EMPTY_QUESTION_MESSAGE
        # Keyed by the canonical URL, which is also what Gemini receives and
        # what the source records; the writer copies URLs from the sources. A
        # re-ask of a recorded video gets the old question pointed at, so its
        # notes never pose as this question's answer (review thread, #140).
        async with run.lock_for(video):
            source = run.sources.get(video)
            if source is not None:
                requested = run.video_questions.get(video)
                if requested != question:
                    return VIDEO_ASKED_AGAIN_MESSAGE.format(
                        question=requested or question
                    )
                return _shown(source)
            if run.videos >= LIMITS.max_videos:
                return NO_VIDEOS_LEFT_MESSAGE
            if not run.has_room():
                return NO_SOURCES_LEFT_MESSAGE
            run.videos += 1
            run.progress(
                VIDEO_PROGRESS_LABEL.format(used=run.videos, cap=LIMITS.max_videos)
            )
            run.reserved += 1
            try:
                # The google-genai instrumentor's spans parent on the current
                # OTel span; without this one they would be orphan traces.
                with start_span("watch_video"):
                    notes = await watch_video(video, question, run.store)
            except VideoUnavailableError:
                logger.warning("ask_video failed", exc_info=True)
                return VIDEO_UNAVAILABLE_MESSAGE
            finally:
                run.reserved -= 1
            if not notes:
                return VIDEO_UNAVAILABLE_MESSAGE
            # Matched loosely: a reply that drops the final period is
            # still "not discussed", never a junk source (correctness review).
            if notes.casefold().startswith(VIDEO_NOT_DISCUSSED.casefold().rstrip(".")):
                return VIDEO_OFF_TOPIC_MESSAGE
            watch_by = run.found_by.get(url)
            title = (
                f"{candidate.title} (watched for {watch_by})"
                if watch_by
                else candidate.title
            )
            source = Source(
                title=VIDEO_TITLE.format(title=title),
                url=video,
                text=notes[: FORECASTER_SOURCES.max_source_chars],
            )
            run.sources[video] = source
            run.video_questions[video] = question
            run.progress(READ_PROGRESS_LABEL.format(count=len(run.sources)))
        return _shown(source)

    return [search_forecaster, read_sources, ask_video]
