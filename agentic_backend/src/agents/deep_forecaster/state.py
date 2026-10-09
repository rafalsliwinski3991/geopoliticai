"""What a forecast carries between its steps, and what its research spent.

`ForecastState` is the graph's typed state (brainstorm design principle 2):
each step returns a partial update and never mutates it. `ForecastRun` is the
graph's run context (`Runtime.context`): the step the forecast is in, which
`forecast()` names if the wall cap ends it. `ResearchRun` is the research
step's own record, which the tools write into and the node reads back;
`ResearchOutcome` is the part of it the answer reports.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from langgraph.types import StreamWriter
from typing_extensions import NotRequired, TypedDict

from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.consts.progress import PROGRESS_NODE
from models import Candidate, Source

logger = logging.getLogger(__name__)


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


@dataclass
class ForecastRun:
    """The graph's run context: where the forecast is, for the wall-cap error."""

    step: str = ""

    def enter(self, label: str, writer: StreamWriter) -> None:
        """Record the step `label` names, log it, and announce it; `label` is a progress const."""
        self.step = label.removesuffix("...")
        logger.info("forecast step: %s", self.step)
        writer({"type": "progress", "node": PROGRESS_NODE, "label": label})


@dataclass
class ResearchRun:
    """One forecast's research budget and everything its tools read.

    Built per call by the `research` node, so each forecast's tools are
    closures over their own record; the scouts share the tool objects and
    therefore the budget. `sources` keeps read order, which numbers the
    sources for every later step.
    """

    writer: StreamWriter
    searches: int = 0
    failed_searches: int = 0
    videos: int = 0
    # Reads in flight: counted against `max_sources` before the fetch awaits,
    # so parallel scouts cannot overshoot the cap (plan review).
    reserved: int = 0
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

    def has_room(self) -> bool:
        """Return whether one more source may be read, counting reads in flight."""
        return len(self.sources) + self.reserved < LIMITS.max_sources

    def lock_for(self, url: str) -> asyncio.Lock:
        """Return the read lock for `url`, creating it on first use."""
        return self.read_locks.setdefault(url, asyncio.Lock())

    def progress(self, label: str) -> None:
        """Emit one progress frame; `label` must be code-produced (see consts)."""
        self.writer({"type": "progress", "node": PROGRESS_NODE, "label": label})
