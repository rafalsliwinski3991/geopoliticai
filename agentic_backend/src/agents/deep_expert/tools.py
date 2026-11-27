"""The deep expert's three tools, over the `services/` web search, page reader, and code sandbox.

Search and read are two tools, not one: a search returns only titles and URLs,
and the model reads the pages it chooses. One combined tool would put up to eight 20,000-character
articles into the transcript per search. `read_source` accepts only URLs a
search in this turn returned. The allow-list is therefore enforced twice: by
`search_allowlisted` and by `fetch_sources`' own domain check. The model can
never make the service fetch an arbitrary URL.

One `search_sources` call is one `search_allowlisted` call, which makes one
Brave request per `EXPERT_SOURCES` batch (three). A turn at the cap makes 45
Brave requests.

`run_python` runs the model's code in the offline sandbox
(`services/code_sandbox.py`), so figures are computed rather than guessed.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from agents.deep_expert.config import LIMITS
from agents.deep_expert.consts.progress import (
    COMPUTE_PROGRESS_LABEL,
    READ_PROGRESS_LABEL,
    SEARCH_PROGRESS_LABEL,
)
from agents.deep_expert.state import ResearchRun
from agents.expert.consts.sources import EXPERT_SOURCES
from services.code_sandbox import CodeRun, run_code
from services.page_reader import fetch_sources
from services.web_search import search_allowlisted
from shared.errors import SandboxUnavailableError
from shared.tracing import start_span

EMPTY_QUERY_MESSAGE = "The query was empty. Search again with a focused query."
UNKNOWN_URL_MESSAGE = (
    "Only URLs returned by `search_sources` in this research can be read."
)
UNREADABLE_MESSAGE = "That page could not be fetched or had no usable article text."
NO_SEARCHES_LEFT_MESSAGE = (
    "No searches left. Do not search again; write the answer from what you have read."
)
EMPTY_CODE_MESSAGE = "The code was empty. Send the Python to run."
NO_COMPUTATIONS_LEFT_MESSAGE = "No computations left. Do not call run_python again; write the answer from what you have."
NO_OUTPUT_MESSAGE = "(The code printed nothing. `print` every result you need.)"
TRUNCATED_NOTE = "\n[Output cut at 10 KB.]"
TIMEOUT_MESSAGE = "The code ran past 10 seconds and was stopped. Simplify it."
OOM_MESSAGE = "The code ran out of memory (256 MB). Use less data."
logger = logging.getLogger(__name__)


def describe_run(result: CodeRun, remaining: int) -> str:
    """Turn one sandbox run into the text the model reads."""
    if result.outcome == "ok":
        body = result.stdout.strip() or NO_OUTPUT_MESSAGE
    elif result.outcome == "timeout":
        body = TIMEOUT_MESSAGE
    elif result.outcome == "oom":
        body = OOM_MESSAGE
    elif result.outcome == "refused":
        body = result.stderr
    else:
        body = f"The code failed (exit {result.exit_code}):\n{result.stderr.strip()}"
    if result.truncated:
        body += TRUNCATED_NOTE
    return f"{body}\n\nComputations left: {remaining}."


def build_tools(run: ResearchRun) -> list[BaseTool]:
    """Return this turn's `search_sources`, `read_source`, and `run_python`, bound to `run`."""

    @tool
    async def search_sources(query: str) -> str:
        """Search the approved news outlets and think tanks for one focused query.

        Returns one result per line as `title | url`. Read promising results
        with `read_source`. Each call spends one search from a fixed budget.
        """
        # The argument is model output. A blank query would fail every batch in
        # `services.web_search.build_batch_query` and surface as a 503 blaming Brave, so it
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

    @tool
    async def run_python(code: str) -> str:
        """Run Python 3 with numpy and pandas in an offline sandbox; returns what it printed.

        Use it when the answer combines several figures from sources you read
        (growth, shares, averages, differences). It cannot read files or the
        internet: paste the numbers into the code and `print` each result.
        Nothing is kept between calls. Each call spends one computation from a
        small fixed budget.
        """
        with start_span("run_python") as span:
            span.set_attributes(
                {
                    "turn.run_index": run.computations + 1,
                    "code.chars": len(code),
                    "code.lines": code.count("\n") + 1,
                }
            )
            if not code.strip():
                span.set_attribute("sandbox.outcome", "empty")
                return EMPTY_CODE_MESSAGE
            if run.computations >= LIMITS.max_computations:
                span.set_attribute("sandbox.outcome", "budget_spent")
                return NO_COMPUTATIONS_LEFT_MESSAGE
            run.computations += 1
            run.progress(
                COMPUTE_PROGRESS_LABEL.format(
                    used=run.computations, cap=LIMITS.max_computations
                )
            )
            try:
                result = await run_code(code)
            except SandboxUnavailableError as exc:
                # A sandbox outage is a hard error, like a search outage.
                span.set_attributes(
                    {
                        "sandbox.outcome": "unreachable",
                        "error.type": type(exc).__name__,
                    }
                )
                raise
            span.set_attributes(
                {
                    "sandbox.outcome": result.outcome,
                    "sandbox.duration_ms": result.duration_ms,
                    "sandbox.exit_code": -1
                    if result.exit_code is None
                    else result.exit_code,
                    "output.chars": len(result.stdout),
                    "output.truncated": result.truncated,
                }
            )
            if result.outcome != "ok":
                span.set_attribute("error.type", result.outcome)
        return describe_run(result, LIMITS.max_computations - run.computations)

    return [search_sources, read_source, run_python]
