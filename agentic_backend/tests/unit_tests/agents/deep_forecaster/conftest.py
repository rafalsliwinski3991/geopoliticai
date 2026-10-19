"""Shared fakes for the deep forecaster's tests; grows per unit."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from agents.deep_forecaster.config import COUNCIL
from agents.deep_forecaster.models import (
    Analysis,
    Ballot,
    Claim,
    ClaimDiscussion,
    DraftedClaims,
    EvidenceRef,
    Stance,
    Vote,
)
from agents.deep_forecaster.state import (
    ForecastRun,
    ForecastState,
    ResearchOutcome,
    ResearchRun,
)
from models import Source

graph_module: Any = importlib.import_module("agents.deep_forecaster.graph")
research_module: Any = importlib.import_module("agents.deep_forecaster.nodes.research")
draft_claims_module: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.draft_claims"
)
write_analysis_module: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.write_analysis"
)
council_module: Any = importlib.import_module("agents.deep_forecaster.council")

TODAY = date(2026, 9, 30)

# A scripted reply that never returns: the step's own timeout, or the wall
# cap, is what ends it.
HANG = object()


@pytest.fixture
def events() -> list[dict[str, Any]]:
    """Progress frames the run's writer appends to."""
    return []


def runtime(events: list[dict[str, Any]]) -> SimpleNamespace:
    """Return a stand-in for the graph's `Runtime` (unit 04 adds `today`)."""
    return SimpleNamespace(
        context=ForecastRun(today=TODAY), stream_writer=events.append
    )


def sources() -> list[Source]:
    """Two sources on two different hosts, three paragraphs (lines) each."""
    return [
        Source(
            "A article",
            "https://carnegieendowment.org/a",
            "Alpha one.\nAlpha two.\nAlpha three.",
            author="Alexander Gabuev",
        ),
        Source(
            "B article",
            "https://reuters.com/b",
            "Beta one.\nBeta two.\nBeta three.",
            author="",
        ),
    ]


def claims() -> list[Claim]:
    """Two claims: Claim 1 quotes [1.1] and [2.2]; Claim 2 quotes [1.3]."""
    return [
        Claim(
            statement="Alpha happens by 2027.",
            deadline=date(2027, 12, 31),
            evidence=[
                EvidenceRef(source=1, paragraph=1),
                EvidenceRef(source=2, paragraph=2),
            ],
        ),
        Claim(
            statement="Beta happens by 2028.",
            deadline=date(2028, 6, 30),
            evidence=[EvidenceRef(source=1, paragraph=3)],
        ),
    ]


def ballot(
    stances: list["Stance"], evidence: dict[int, list[int]] | None = None
) -> Ballot:
    """One member's ballot: one vote per given stance, in claim order."""
    evidence = evidence or {}
    votes = [
        Vote(
            claim=number,
            stance=stance,
            reason=f"Reason {number}.",
            evidence=evidence.get(number, [1] if stance != "unsure" else []),
        )
        for number, stance in enumerate(stances, start=1)
    ]
    return Ballot(votes=votes)


def state(
    *,
    claims_list: list[Claim] | None = None,
    research: ResearchOutcome | None = None,
    round_1: dict[int, Ballot] | None = None,
    round_2: dict[int, Ballot] | None = None,
) -> ForecastState:
    """A `ForecastState` with two sources, two claims, and the given ballots."""
    claims_list = claims_list or claims()
    round_1 = (
        round_1
        if round_1 is not None
        else {member: ballot(["for", "unsure"]) for member in range(1, 8)}
    )
    return ForecastState(
        question="Will it happen?",
        sources=sources(),
        research=research or ResearchOutcome(2, 0, False),
        claims=claims_list,
        ballots_round_1=round_1,
        ballots_round_2=round_2 or {},
    )


@dataclass
class PinnedRun(ForecastRun):
    """`ForecastRun` whose "today" is `TODAY`, so claim deadlines never age."""

    today: date = TODAY


def passing_analysis() -> Analysis:
    """An analysis of `claims()` that passes every verify check."""
    return Analysis(
        overview="The council leans yes. [A](source:1)",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha. [A](source:1)"),
            ClaimDiscussion(claim=2, discussion="Beta. [B](source:2)"),
        ],
    )


# Unit 05: the plan's six named broken analyses (plan §5), each a passing
# analysis with exactly one defect a rewrite can fix. Every one carries the
# marker `INJECTED-7f3a` in its prose, and inside its defective link or
# citation where it has one, so a defect that echoed the writer's own text
# would leak the marker.
MARKER = "INJECTED-7f3a"
MARKER_URL = f"https://carnegieendowment.org/{MARKER}"

MISSING_CLAIM = Analysis(
    overview=f"The council leans yes. [A](source:1) — {MARKER} saw it.",
    claims=[ClaimDiscussion(claim=1, discussion="Alpha reasons. [A](source:1)")],
)
EMPTY_SECTION = Analysis(
    overview="The council leans yes. [A](source:1)",
    claims=[
        ClaimDiscussion(claim=1, discussion=""),
        ClaimDiscussion(
            claim=2, discussion=f"Beta reasons. [B](source:2) — {MARKER} saw it."
        ),
    ],
)
RAW_URL = Analysis(
    overview=f"The council leans yes. [A](source:1). See [more]({MARKER_URL}).",
    claims=[
        ClaimDiscussion(
            claim=1, discussion=f"Alpha reasons. [A](source:1) — {MARKER} saw it."
        ),
        ClaimDiscussion(claim=2, discussion="Beta reasons. [B](source:2)"),
    ],
)
UNLINKABLE_CITATION = Analysis(
    overview=f'The council leans yes. See [a {MARKER} note](source:1 "t").',
    claims=[
        ClaimDiscussion(claim=1, discussion=f"Alpha reasons. {MARKER} saw it."),
        ClaimDiscussion(claim=2, discussion="Beta reasons."),
    ],
)
NO_CITATION = Analysis(
    overview=f"The council leans yes. {MARKER} agrees.",
    claims=[
        ClaimDiscussion(claim=1, discussion="Alpha reasons."),
        ClaimDiscussion(claim=2, discussion="Beta reasons."),
    ],
)
UNREAD_SOURCE = Analysis(
    overview=f"The council leans yes. [{MARKER}](source:9)",
    claims=[
        ClaimDiscussion(claim=1, discussion="Alpha reasons. [A](source:1)"),
        ClaimDiscussion(claim=2, discussion="Beta reasons. [B](source:2)"),
    ],
)

# The exact defect `find_defect` must return for each named analysis, written
# by hand from the rules, never computed.
MISSING_CLAIM_DEFECT = (
    "The analysis did not discuss every claim exactly once: it needs one "
    "section for each of claims 1 and 2 and wrote sections for 1."
)
EMPTY_SECTION_DEFECT = "The analysis left a section empty: claim 1."
RAW_URL_DEFECT = (
    "The analysis wrote a URL; it must cite sources only as [anchor](source:N)."
)
UNLINKABLE_CITATION_DEFECT = (
    "The analysis wrote a citation the answer cannot link; write each one "
    "exactly as [anchor](source:N)."
)
NO_CITATION_DEFECT = "The analysis cited none of the sources it read."
UNREAD_SOURCE_DEFECT = (
    "The analysis cites 1 source number outside 1 to 2, the sources the "
    "forecast read; cite whole source numbers such as (source:3)."
)

DEFECTS = [
    pytest.param(MISSING_CLAIM, MISSING_CLAIM_DEFECT, id="a missing claim"),
    pytest.param(EMPTY_SECTION, EMPTY_SECTION_DEFECT, id="an empty section"),
    pytest.param(RAW_URL, RAW_URL_DEFECT, id="a raw url"),
    pytest.param(
        UNLINKABLE_CITATION, UNLINKABLE_CITATION_DEFECT, id="an unlinkable citation"
    ),
    pytest.param(NO_CITATION, NO_CITATION_DEFECT, id="no citation"),
    pytest.param(UNREAD_SOURCE, UNREAD_SOURCE_DEFECT, id="an unread source"),
]


class ScriptedWriter:
    """Stands in for the writer's model call: returns its script in order.

    Each reply is an `Analysis`, an exception to raise, or `HANG`. Every
    brief it is sent is recorded, and a call past the end of the script
    fails the test, so "the writer ran exactly twice" is provable.
    """

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.briefs: list[str] = []

    async def __call__(
        self, system: str, messages: Any, schema: Any, **kwargs: Any
    ) -> Analysis:
        self.briefs.append(str(messages[-1].content))
        if not self.replies:
            raise AssertionError("the writer was called more often than scripted")
        reply = self.replies.pop(0)
        if reply is HANG:
            await asyncio.sleep(3600)
        if isinstance(reply, BaseException):
            raise reply
        # The script's remaining reply is the analysis; narrowed, because
        # mypy --strict refuses a returned Any (as `council._attempt` does).
        analysis: Analysis = reply
        return analysis

    @property
    def calls(self) -> int:
        return len(self.briefs)


@dataclass
class ForecastRig:
    """The real forecast graph, with one fake at each of its four seams.

    The defaults run a clean forecast: research reads `sources()` in two
    searches, the drafter returns `claims()`, all seven seats vote
    `ballot(["for", "unsure"])` in both rounds, and the writer returns
    `passing_analysis()` once. A test changes one field to break one seam,
    then awaits `run()`. The record fields say how far the run got.
    """

    sources: list[Source] = field(default_factory=sources)
    searches: int = 2
    failed_searches: int = 0
    research_error: BaseException | None = None
    drafted: Any = field(default_factory=claims)  # list[Claim], an exception, or HANG
    # Member number -> reply, per round; a member missing here votes the default.
    round_1: dict[int, Any] = field(default_factory=dict)
    round_2: dict[int, Any] = field(default_factory=dict)
    writer: ScriptedWriter = field(
        default_factory=lambda: ScriptedWriter(passing_analysis())
    )
    drafter_calls: int = 0
    member_calls: list[tuple[int, int]] = field(default_factory=list)  # (round, member)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module, "ForecastRun", PinnedRun)
        monkeypatch.setattr(research_module, "build_research_agent", self._agent)
        monkeypatch.setattr(draft_claims_module, "ainvoke_structured", self._draft)
        monkeypatch.setattr(council_module, "member_model", self._member)
        monkeypatch.setattr(write_analysis_module, "ainvoke_structured", self._write)

    async def run(self) -> str:
        answer: str = await graph_module.forecast("Will it happen?")
        return answer

    def _agent(self, run: ResearchRun) -> Any:
        rig = self

        class Agent:
            async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
                if rig.research_error is not None:
                    raise rig.research_error
                run.searches = rig.searches
                run.failed_searches = rig.failed_searches
                for source in rig.sources:
                    run.sources[source.url] = source
                return {"messages": []}

        return Agent()

    async def _draft(
        self, system: str, messages: Any, schema: Any, **kwargs: Any
    ) -> Any:
        self.drafter_calls += 1
        if self.drafted is HANG:
            await asyncio.sleep(3600)
        if isinstance(self.drafted, BaseException):
            raise self.drafted
        return DraftedClaims(claims=self.drafted)

    def _member(self, seat: Any, model: str, *, max_retries: int) -> Any:
        rig = self
        member = [s.model for s in COUNCIL].index(model) + 1

        class Member:
            async def ainvoke(self, messages: Any) -> Any:
                round_number = 1 + sum(1 for _, m in rig.member_calls if m == member)
                rig.member_calls.append((round_number, member))
                script = rig.round_1 if round_number == 1 else rig.round_2
                reply = script.get(member, ballot(["for", "unsure"]))
                if reply is HANG:
                    await asyncio.sleep(3600)
                if isinstance(reply, BaseException):
                    raise reply
                return reply

        return Member()

    async def _write(
        self, system: str, messages: Any, schema: Any, **kwargs: Any
    ) -> Analysis:
        """Delegate to the `writer` field at call time, so a test may swap it."""
        return await self.writer(system, messages, schema, **kwargs)


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> ForecastRig:
    """A `ForecastRig` already installed; tests change its fields before `run()`."""
    forecast_rig = ForecastRig()
    forecast_rig.install(monkeypatch)
    return forecast_rig


def shorten_step(monkeypatch: pytest.MonkeyPatch, name: str, seconds: float) -> None:
    """Give one graph step a short LangGraph node timeout (`graph.STEPS`)."""
    monkeypatch.setattr(
        graph_module,
        "STEPS",
        tuple(
            (step, node, seconds if step == name else timeout)
            for step, node, timeout in graph_module.STEPS
        ),
    )


def shorten_limit(
    monkeypatch: pytest.MonkeyPatch, module: str, **limits: float
) -> None:
    """Replace fields of a module's frozen `LIMITS` (e.g. `wall_seconds`)."""
    target = importlib.import_module(f"agents.deep_forecaster.{module}")
    monkeypatch.setattr(target, "LIMITS", dataclasses.replace(target.LIMITS, **limits))
