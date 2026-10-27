"""What a forecast carries between its steps, and what its research spent.

`ForecastState` is the graph's typed state (brainstorm design principle 2):
each step returns a partial update and never mutates it. `ForecastRun` is the
graph's run context (`Runtime.context`): the step the forecast is in, which
`forecast()` names if the wall cap ends it. `ResearchRun` is the research
step's own record, which the tools write into and the node reads back;
`ResearchOutcome` is the part of it the answer reports. State here is what
LangGraph channels carry between nodes; the `*Run` records are mutable work
contexts bound to one invocation and never written back into the graph
(review thread, #142). The drafter's and council's message models live in
`models.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from langgraph.store.base import BaseStore
from langgraph.types import StreamWriter
from typing_extensions import NotRequired, TypedDict

from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.consts.progress import PROGRESS_NODE
from agents.deep_forecaster.models import Analysis, Ballot, Claim, Verdict
from models import Candidate, Source
from services.page_reader import FETCH_CONCURRENCY
from shared.frames import ProgressFrame

logger = logging.getLogger(__name__)


def _utc_today() -> date:
    """Return today's date in UTC, the day a forecast is made."""
    return datetime.now(UTC).date()


@dataclass(frozen=True)
class ClaimTally:
    """The final round's count for one claim (Q7)."""

    claim: int
    verdict: Verdict
    votes_for: int
    against: int
    unsure: int
    voting: int


@dataclass(frozen=True)
class ResearchOutcome:
    """How research ended, which the answer's evidence line reports.

    A failed search and the time box are not errors (user decision
    2026-09-30): the forecast continues on what was read, and the answer
    says so instead of reading as a full research step.
    """

    searches: int
    failed_searches: int
    timed_out: bool


class ForecastState(TypedDict):
    """One forecast's state. `question` is the only input; each step adds its key."""

    question: str
    sources: NotRequired[list[Source]]
    research: NotRequired[ResearchOutcome]
    claims: NotRequired[list[Claim]]
    # Keyed by member number (1-7). A member missing from round 1 was dropped;
    # one missing from round 2 keeps its round-1 ballot (`council.final_ballots`).
    ballots_round_1: NotRequired[dict[int, Ballot]]
    ballots_round_2: NotRequired[dict[int, Ballot]]
    # Written by `tally`: each member's latest ballot (`council.final_ballots`),
    # which `write_analysis` and `verify` read instead of rebuilding it.
    final_ballots: NotRequired[dict[int, Ballot]]
    tally: NotRequired[list[ClaimTally]]
    analysis: NotRequired[Analysis]
    # Set by `verify` on the analysis's first defect and read by the writer's
    # one rewrite (brainstorm 2026Oct16 Q8); its presence means the rewrite
    # is spent. Written by code, never by a model.
    feedback: NotRequired[str]
    answer: NotRequired[str]


@dataclass
class ForecastRun:
    """The graph's run context: the step the forecast is in, and its "today".

    `today` is the forecast's as-of date: always the UTC date in the app; tests
    pin it (`PinnedRun`) so claim deadlines never age.
    """

    step: str = ""
    today: date = field(default_factory=_utc_today)
    # The orchestrator's store, for `research.ask_video`'s video-notes cache;
    # None at the root (review thread, #151).
    store: BaseStore | None = None

    def enter(self, label: str, writer: StreamWriter) -> None:
        """Record the step `label` names, log it, and announce it; `label` is a progress const."""
        self.step = label.removesuffix("...")
        logger.info("forecast step: %s", self.step)
        writer(ProgressFrame(node=PROGRESS_NODE, label=label))


@dataclass
class ResearchRun:
    """One forecast's research budget and everything its tools read.

    Built per call by the `research` node, so each forecast's tools are
    closures over their own record; the scouts share the tool objects and
    therefore the budget. `sources` keeps read order, which numbers the
    sources for every later step.
    """

    writer: StreamWriter
    # The orchestrator's store, for `video.watch_video`'s cache; None at the root.
    store: BaseStore | None = None
    searches: int = 0
    failed_searches: int = 0
    videos: int = 0
    # Reads in flight: counted against `max_sources` before the fetch awaits,
    # so parallel scouts cannot overshoot the cap (plan review).
    reserved: int = 0
    # What the `forecast_research` span reports beyond the budgets (brainstorm
    # 2026Oct19, span rule): which forecasters were searched, searches that
    # found nothing, and pages with no usable text.
    forecasters_searched: set[str] = field(default_factory=set)
    empty_searches: int = 0
    unreadable_pages: int = 0
    candidates: dict[str, Candidate] = field(default_factory=dict)
    # Which forecaster's search returned each candidate; a video's notes are
    # titled with it, so the record says whose page pointed at the video
    # (review thread, #140).
    found_by: dict[str, str] = field(default_factory=dict)
    # The question each recorded video already answered, so `ask_video` can
    # say so instead of presenting old notes as a new question's answer (review thread, #140).
    video_questions: dict[str, str] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    # One in-flight read per URL, as the deep expert's (review thread, #129):
    # a second concurrent call waits, then finds the source recorded.
    read_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    search_gate: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(LIMITS.max_search_concurrency)
    )
    # Page fetches bound the same way: `fetch_sources` builds its per-call
    # semaphore (services/page_reader.py) around a call's own candidates, so without this
    # gate a batch read would put `max_batch` GETs on a forecaster's site at
    # once and parallel scouts would multiply that (review thread).
    read_gate: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(FETCH_CONCURRENCY)
    )

    def room_left(self) -> int:
        """Return how many more sources may be read, counting reads in flight."""
        return LIMITS.max_sources - len(self.sources) - self.reserved

    def has_room(self) -> bool:
        """Return whether one more source may be read, counting reads in flight."""
        return self.room_left() > 0

    def lock_for(self, url: str) -> asyncio.Lock:
        """Return the read lock for `url`, creating it on first use."""
        return self.read_locks.setdefault(url, asyncio.Lock())

    def progress(self, label: str) -> None:
        """Emit one progress frame; `label` must be code-produced (see consts)."""
        self.writer(ProgressFrame(node=PROGRESS_NODE, label=label))
