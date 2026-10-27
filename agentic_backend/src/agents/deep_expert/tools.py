"""The deep expert's two research tools, over the shared `services/web_search.py` and `services/page_reader.py` boundary.

Two tools, not one: a search returns only titles and URLs, and the model reads
the pages it chooses. One combined tool would put up to eight 20,000-character
articles into the transcript per search. `read_source` accepts only URLs a
search in this turn returned. The allow-list is therefore enforced twice: by
`search_allowlisted` and by `fetch_sources`' own domain check. The model can
never make the service fetch an arbitrary URL.

One `search_sources` call is one `search_allowlisted` call, which makes one
Brave request per `EXPERT_SOURCES` batch (three). A turn at the cap makes 45
Brave requests.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from agents.deep_expert.config import LIMITS
from agents.deep_expert.consts.progress import (
    READ_PROGRESS_LABEL,
    SEARCH_PROGRESS_LABEL,
)
from agents.deep_expert.state import ResearchRun
from agents.expert.consts.sources import EXPERT_SOURCES
from services.page_reader import fetch_sources
from services.web_search import search_allowlisted

EMPTY_QUERY_MESSAGE = "The query was empty. Search again with a focused query."
UNKNOWN_URL_MESSAGE = (
    "Only URLs returned by `search_sources` in this research can be read."
)
UNREADABLE_MESSAGE = "That page could not be fetched or had no usable article text."
NO_SEARCHES_LEFT_MESSAGE = (
    "No searches left. Do not search again; write the answer from what you have read."
)
logger = logging.getLogger(__name__)


def build_tools(run: ResearchRun) -> list[BaseTool]:
    """Return this turn's `search_sources` and `read_source`, bound to `run`."""

    @tool
    async def search_sources(query: str) -> str:
        """Search the approved news outlets and think tanks for one focused query.

        Returns one result per line as `title | url`. Read promising results
        with `read_source`. Each call spends one search from a fixed budget.
        """
        # The argument is model output. A blank query would fail every batch in
        # `search.build_batch_query` and surface as a 503 blaming Brave, so it
        # is refused here, before it spends anything.
        query = " ".join(query.split())
        if not query:
            return EMPTY_QUERY_MESSAGE
        if run.searches >= LIMITS.max_searches:
            # Soft stop (plan review, user decision): no Brave call, so spend
            # is bounded exactly as a hard error would bound it, and parallel
            # subagents that overshoot do not kill a nearly finished turn.
            return NO_SEARCHES_LEFT_MESSAGE
        run.searches += 1
        run.progress(
            SEARCH_PROGRESS_LABEL.format(used=run.searches, cap=LIMITS.max_searches)
        )
        # SearchUnavailableError propagates: a search outage is a hard error.
        candidates = await search_allowlisted(query, EXPERT_SOURCES)
        for candidate in candidates:
            run.candidates.setdefault(candidate.url, candidate)
        remaining = LIMITS.max_searches - run.searches
        logger.info("deep search %d: %d candidates", run.searches, len(candidates))
        footer = f"Searches left: {remaining}."
        if not candidates:
            return f"No approved results for that query.\n\n{footer}"
        lines = "\n".join(f"{c.title} | {c.url}" for c in candidates)
        return f"{lines}\n\n{footer}"

    @tool
    async def read_source(url: str) -> str:
        """Read the article text at one URL that `search_sources` returned.

        Cite the page with exactly this URL.
        """
        candidate = run.candidates.get(url)
        if candidate is None:
            return UNKNOWN_URL_MESSAGE
        # One in-flight read per URL (review thread, #129 c4142559750): a
        # concurrent call for the same URL waits here, then finds the source
        # cached and skips the fetch, instead of fetching first and
        # duplicating the progress event.
        async with run.lock_for(url):
            source = run.sources.get(url)
            if source is None:
                fetched = await fetch_sources([candidate], EXPERT_SOURCES)
                if not fetched:
                    return UNREADABLE_MESSAGE
                source = fetched[0]
                # Keyed by the URL the model asked for, which is the one it
                # will cite, even when a redirect changed `source.url`.
                run.sources[url] = source
                run.progress(READ_PROGRESS_LABEL.format(count=len(run.sources)))
        return f"--- SOURCE ---\nTitle: {source.title}\nURL: {url}\n\n{source.text}"

    return [search_sources, read_source]
