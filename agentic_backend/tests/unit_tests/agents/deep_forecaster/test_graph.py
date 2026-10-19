"""Unit tests for `agents.deep_forecaster.graph`."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeTimeoutError
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.deep_forecaster.config import COUNCIL
from agents.deep_forecaster.models import (
    Analysis,
    Ballot,
    Claim,
    ClaimDiscussion,
    EvidenceRef,
)
from agents.deep_forecaster.state import ForecastRun, ResearchRun
from models import (
    LLMInvocationError,
    NoSourcesError,
    ResearchLimitError,
    SearchUnavailableError,
    Source,
)
from unit_tests.agents.deep_forecaster.conftest import (
    HANG,
    TODAY,
    ForecastRig,
    ScriptedWriter,
    ballot,
    claims,
    shorten_limit,
    shorten_step,
    sources,
)

graph_module: Any = importlib.import_module("agents.deep_forecaster.graph")
research_node: Any = importlib.import_module("agents.deep_forecaster.nodes.research")
draft_claims_node: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.draft_claims"
)
write_analysis_node: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.write_analysis"
)
council_module: Any = importlib.import_module("agents.deep_forecaster.council")

STEP_NAMES = [
    "research",
    "draft_claims",
    "council_round_1",
    "council_round_2",
    "tally",
    "write_analysis",
    "verify",
]

SEAT_DOWN = RuntimeError("provider 500")
# A ballot voting only claim 1: the shape trace 8a80df9c saw in round 2.
BALLOT_MISSING_A_CLAIM = ballot(["for"])
BALLOT_CITING_AN_UNQUOTED_SOURCE = ballot(["for", "for"], evidence={2: [2]})
# The pinned run's "today" plus one day: the nearest deadline a claim may carry.
TOMORROW = TODAY + timedelta(days=1)
# Short node, member and wall limits, so a hung fake ends the run in milliseconds.
SHORT_STEP_SECONDS = 0.05
SHORT_MEMBER_SECONDS = 0.05
SHORT_WALL_SECONDS = 0.2


def n_claims(count: int) -> list[Claim]:
    """`count` distinct claims, each due `TOMORROW` and quoting source 1."""
    statements = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    return [
        Claim(
            statement=f"{statements[number]} happens.",
            deadline=TOMORROW,
            evidence=[EvidenceRef(source=1, paragraph=1)],
        )
        for number in range(count)
    ]


def analysis_of(drafted: list[Claim]) -> Analysis:
    """An analysis with one section per claim, citing only the first source."""
    return Analysis(
        overview="The council leans yes. [A](https://carnegieendowment.org/a)",
        claims=[
            ClaimDiscussion(
                claim=number,
                discussion=f"Section {number}. [A](https://carnegieendowment.org/a)",
            )
            for number in range(1, len(drafted) + 1)
        ],
    )


def four_vote_ballot() -> Ballot:
    """A ballot voting 'for' on all four claims, citing the source they quote."""
    return ballot(
        ["for", "for", "for", "for"],
        evidence={number: [1] for number in range(1, 5)},
    )


def test_the_graph_has_exactly_the_seven_steps() -> None:
    assert [name for name, _, _ in graph_module.STEPS] == STEP_NAMES


def test_the_steps_run_in_a_fixed_chain() -> None:
    graph = graph_module.build_graph()
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert edges == {
        ("__start__", "research"),
        ("research", "draft_claims"),
        ("draft_claims", "council_round_1"),
        ("council_round_1", "council_round_2"),
        ("council_round_2", "tally"),
        ("tally", "write_analysis"),
        ("write_analysis", "verify"),
        ("verify", "__end__"),
    }


def test_no_step_is_named_like_an_answer_node() -> None:
    names = {name for name, _, _ in graph_module.STEPS}
    assert names & {"answer", "chat", "write"} == set()


def test_build_graph_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    graph_module.build_graph()


def test_the_single_call_steps_carry_node_timeouts() -> None:
    timeouts = {name: timeout for name, _, timeout in graph_module.STEPS}
    assert timeouts["draft_claims"] == 120.0
    assert timeouts["write_analysis"] == 150.0
    assert all(
        timeout is None
        for name, _, timeout in graph_module.STEPS
        if name not in {"draft_claims", "write_analysis"}
    )


@pytest.mark.anyio
async def test_forecast_returns_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            recorded["config"] = config
            recorded["context"] = context
            return {"answer": "The answer."}

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    # Act
    answer = await graph_module.forecast("Will it happen?")
    # Assert
    assert answer == "The answer."
    assert recorded["config"] is graph_module.NO_CHECKPOINTER_CONFIG
    assert isinstance(recorded["context"], ForecastRun)


@pytest.mark.anyio
async def test_the_wall_cap_names_the_step(monkeypatch: pytest.MonkeyPatch) -> None:
    record = {"cancelled": False}

    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            context.step = "Council voting, round 1 of 2"
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                record["cancelled"] = True
                raise
            return {"answer": "x"}

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    monkeypatch.setattr(
        graph_module,
        "LIMITS",
        dataclasses.replace(graph_module.LIMITS, wall_seconds=0.05),
    )
    # Act
    with pytest.raises(ResearchLimitError) as raised:
        await graph_module.forecast("Will it happen?")
    # Assert
    assert raised.value.status == 504
    assert str(raised.value).endswith("during this step: Council voting, round 1 of 2.")
    assert record["cancelled"] is True


@pytest.mark.anyio
async def test_an_inner_timeout_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            raise TimeoutError("inner")

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(LLMInvocationError, match="The forecast failed."):
        await graph_module.forecast("Will it happen?")


@pytest.mark.anyio
async def test_a_step_timeout_is_a_research_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            context.step = "Drafting the claims"
            raise NodeTimeoutError("draft_claims", 90.5, kind="run", run_timeout=90.0)

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(ResearchLimitError) as raised:
        await graph_module.forecast("Will it happen?")
    assert raised.value.status == 504
    assert "90-second" in str(raised.value)
    assert "Drafting the claims" in str(raised.value)


@pytest.mark.anyio
async def test_a_pipeline_error_keeps_its_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            raise NoSourcesError("nothing readable")

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(NoSourcesError):
        await graph_module.forecast("Will it happen?")


@pytest.mark.anyio
async def test_an_arbitrary_failure_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            raise RuntimeError("bug")

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(LLMInvocationError, match="The forecast failed."):
        await graph_module.forecast("Will it happen?")


@pytest.mark.anyio
async def test_a_forecast_runs_every_step_once_inside_a_checkpointed_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The research step: a fake agent that records two sources on two hosts.
    def mutate(run: ResearchRun) -> None:
        run.searches = 2
        run.sources["https://a.example/1"] = Source(
            "A article", "https://a.example/1", "Alpha one.\nAlpha two.\nAlpha three."
        )
        run.sources["https://b.example/2"] = Source(
            "B article", "https://b.example/2", "Beta one.\nBeta two.\nBeta three."
        )

    class FakeAgent:
        def __init__(self, run: ResearchRun) -> None:
            self.run = run

        async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
            mutate(self.run)
            return {"messages": []}

    monkeypatch.setattr(
        research_node, "build_research_agent", lambda run: FakeAgent(run)
    )

    # The two structured calls: claims, then the analysis.
    async def fake_claims(
        system: Any, messages: Any, schema: Any, **kwargs: Any
    ) -> Any:
        return importlib.import_module("agents.deep_forecaster.models").DraftedClaims(
            claims=claims()
        )

    async def fake_analysis(
        system: Any, messages: Any, schema: Any, **kwargs: Any
    ) -> Any:
        return Analysis(
            overview="The council leans yes. [A](https://a.example/1)",
            claims=[
                ClaimDiscussion(claim=1, discussion="Alpha. [A](https://a.example/1)"),
                ClaimDiscussion(claim=2, discussion="Beta. [B](https://b.example/2)"),
            ],
        )

    monkeypatch.setattr(draft_claims_node, "ainvoke_structured", fake_claims)
    monkeypatch.setattr(write_analysis_node, "ainvoke_structured", fake_analysis)

    # The council: fakes keyed by model id, scripted per the plan's scenario.
    member_calls: list[tuple[str, int, str]] = []
    model_reads: list[str] = []
    scripted = {
        # Member 3's model fails round 1; the seat is dropped and sits round 2 out.
        COUNCIL[2].model: {"fail_first": True},
        # Member 7's model fails round 2, and it keeps its round-1 vote.
        COUNCIL[6].model: {"fail_second": True},
    }
    counters: dict[str, int] = {}

    class FakeModel:
        def __init__(self, model: str, max_retries: int) -> None:
            self.model = model
            self.max_retries = max_retries

        async def ainvoke(self, messages: Any) -> Any:
            counters[self.model] = counters.get(self.model, 0) + 1
            model_reads.append("\n".join(str(m.content) for m in messages))
            script = scripted.get(self.model)
            count = counters[self.model]
            if script is not None and (
                (script.get("fail_first") and count == 1)
                or (script.get("fail_second") and count >= 2)
            ):
                member_calls.append((self.model, self.max_retries, "failed"))
                raise RuntimeError("planned failure")
            member_calls.append((self.model, self.max_retries, "ok"))
            return ballot(["for", "unsure"])

    def fake_member_model(seat: Any, model: str, *, max_retries: int) -> FakeModel:
        return FakeModel(model, max_retries)

    monkeypatch.setattr(council_module, "member_model", fake_member_model)

    # The parent graph, with a saver, calls `forecast()` from a node.
    class ParentState(TypedDict):
        answer: str

    saver = InMemorySaver()

    async def parent_node(state: ParentState) -> dict[str, Any]:
        answer = await graph_module.forecast("Will it happen?")
        return {"answer": answer}

    builder: Any = StateGraph(ParentState, context_schema=ForecastRun)
    builder.add_node("forecast", parent_node)
    builder.add_edge(START, "forecast")
    builder.add_edge("forecast", END)
    parent = builder.compile(checkpointer=saver)

    labels: list[str] = []
    from agents.deep_forecaster.consts.progress import (
        CLAIMS_LABEL,
        RESEARCH_LABEL,
        ROUND_LABEL,
        VERIFY_LABEL,
        WRITE_LABEL,
    )

    expected_labels = [
        RESEARCH_LABEL,
        CLAIMS_LABEL,
        ROUND_LABEL.format(round=1),
        ROUND_LABEL.format(round=2),
        WRITE_LABEL,
        VERIFY_LABEL,
    ]

    # Act
    async for chunk in parent.astream(
        {"answer": ""},
        config={"configurable": {"thread_id": "t"}},
        context=ForecastRun(),
        stream_mode="custom",
        subgraphs=True,
    ):
        if isinstance(chunk[1], dict) and "label" in chunk[1]:
            labels.append(chunk[1]["label"])
    final = await parent.aget_state({"configurable": {"thread_id": "t"}})
    result = final.values
    answer_text = str(result["answer"])
    # Assert
    assert labels == expected_labels
    assert "### Claim 1: ACCEPTED" in answer_text
    assert "### Claim 2: UNRESOLVED" in answer_text
    assert "Members voting: 6 of 7 (1 unavailable)." in answer_text
    assert (
        "Round 2: 1 of 6 kept their round-1 vote because they did not answer."
        in answer_text
    )
    assert (
        "Evidence: 2 sources read from 2 sites. The council voted on 3 passages "
        "quoted from 2 of them." in answer_text
    )
    assert "- Member 7 (round-1 vote):" in answer_text
    # 13 member calls: round 1 is 7 seats with member 3 failing; round 2 is the
    # 6 round-1 voters with member 7 failing; 2 calls fail.
    assert len(member_calls) == 13
    assert len([call for call in member_calls if call[2] == "failed"]) == 2
    assert {call[0] for call in member_calls if call[2] == "failed"} == {
        COUNCIL[2].model,
        COUNCIL[6].model,
    }
    # No member read the text of a paragraph no claim points at.
    assert not any("Alpha two." in read for read in model_reads)
    # The parent's saver holds no child checkpoint.
    namespaces: set[str] = set()
    async for checkpoint in saver.alist({"configurable": {"thread_id": "t"}}):
        namespaces.add(checkpoint.config["configurable"]["checkpoint_ns"])
    assert namespaces == {""}


@pytest.mark.anyio
async def test_the_parent_store_reaches_the_research_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child graph takes its parent's store: the forecaster's cache reads it."""
    from langgraph.store.memory import InMemoryStore

    received: dict[str, Any] = {}

    class FakeAgent:
        def __init__(self, run: ResearchRun) -> None:
            received["run"] = run
            self.run = run

        async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
            self.run.sources["https://a.example/1"] = Source(
                "A", "https://a.example/1", "One."
            )
            return {"messages": []}

    monkeypatch.setattr(
        research_node, "build_research_agent", lambda run: FakeAgent(run)
    )

    class ParentState(TypedDict):
        answer: str

    store = InMemoryStore()

    async def parent_node(state: ParentState) -> dict[str, Any]:
        await research_node.research(
            {"question": "q"},
            SimpleNamespace(
                context=ForecastRun(), stream_writer=lambda e: None, store=store
            ),
        )
        return {"answer": ""}

    builder: Any = StateGraph(ParentState)
    builder.add_node("n", parent_node)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    parent = builder.compile(checkpointer=InMemorySaver(), store=store)

    # Act
    await parent.ainvoke({"answer": ""}, config={"configurable": {"thread_id": "t"}})
    # Assert: the ResearchRun the fake was built with carries the parent's store.
    assert received["run"].store is store


@pytest.mark.anyio
async def test_a_forecast_that_reads_no_source_fails_before_drafting(
    rig: ForecastRig,
) -> None:
    """Research that reads nothing is a 422: no claims are drafted on thin air."""
    # Arrange
    rig.sources = []
    # Act
    with pytest.raises(NoSourcesError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 422
    assert str(raised.value) == (
        "The forecast found no readable writing by the forecasters on this question."
    )
    assert rig.drafter_calls == 0


@pytest.mark.anyio
async def test_a_forecast_whose_every_search_failed_reports_an_outage(
    rig: ForecastRig,
) -> None:
    """Every search failing is an outage (503), not an empty-reading 422."""
    # Arrange
    rig.sources = []
    rig.searches = 3
    rig.failed_searches = 3
    # Act
    with pytest.raises(SearchUnavailableError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 503
    assert str(raised.value) == "Every search for this forecast failed."
    assert rig.drafter_calls == 0


@pytest.mark.anyio
async def test_a_crashed_research_agent_fails_the_forecast(
    rig: ForecastRig,
) -> None:
    """A research crash is a 502 naming the research step, never a partial forecast."""
    # Arrange
    rig.research_error = RuntimeError("boom")
    # Act
    with pytest.raises(LLMInvocationError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 502
    assert str(raised.value) == "The forecast's research failed."
    assert rig.drafter_calls == 0


@pytest.mark.anyio
async def test_one_failed_search_with_a_source_read_still_forecasts(
    rig: ForecastRig,
) -> None:
    """A failed search is not an error while a source was read: the answer says so."""
    # Arrange
    rig.sources = sources()[:1]
    rig.searches = 3
    rig.failed_searches = 2
    rig.writer = ScriptedWriter(analysis_of(claims()))
    # Act
    answer = await rig.run()
    # Assert
    assert "2 of 3 searches failed." in answer


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("drafted", "expected_message"),
    [
        pytest.param(
            n_claims(1),
            "The forecast drafted 1 claims; it needs 2 to 4.",
            id="one claim",
        ),
        pytest.param(
            n_claims(5),
            "The forecast drafted 5 claims; it needs 2 to 4.",
            id="five claims",
        ),
        pytest.param(
            [
                Claim(
                    statement="",
                    deadline=TOMORROW,
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ]
            + n_claims(1),
            "The forecast drafted an empty claim.",
            id="an empty statement",
        ),
        pytest.param(
            n_claims(1) + n_claims(1),
            "The forecast drafted the same claim twice.",
            id="the same claim twice",
        ),
        pytest.param(
            [
                Claim(
                    statement="Alpha happens. https://reuters.com/b",
                    deadline=TOMORROW,
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ]
            + n_claims(1),
            "The forecast wrote a claim statement with a link or a line break.",
            id="a link in a statement",
        ),
        pytest.param(
            [
                Claim(
                    statement="Alpha happens\nby 2027.",
                    deadline=TOMORROW,
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ]
            + n_claims(1),
            "The forecast wrote a claim statement with a link or a line break.",
            id="a line break in a statement",
        ),
        pytest.param(
            [
                Claim(
                    statement="Alpha happens.",
                    deadline=TODAY,
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ]
            + n_claims(1),
            "The forecast drafted a claim whose deadline is not in the future.",
            id="a deadline of today",
        ),
        pytest.param(
            [
                Claim(
                    statement="Alpha happens.",
                    deadline=TOMORROW,
                    evidence=[EvidenceRef(source=1, paragraph=99)],
                )
            ]
            + n_claims(1),
            "The forecast drafted a claim with no passage its sources contain.",
            id="no passage the sources contain",
        ),
    ],
)
async def test_a_broken_claim_set_stops_before_the_council(
    rig: ForecastRig, drafted: list[Claim], expected_message: str
) -> None:
    """A claim set breaking a `checked_claims` rule is a 502 before any seat votes."""
    # Arrange
    rig.drafted = drafted
    # Act
    with pytest.raises(LLMInvocationError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 502
    assert str(raised.value) == expected_message
    assert rig.member_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "drafted",
    [
        pytest.param(n_claims(2), id="two claims"),
        pytest.param(n_claims(4), id="four claims"),
    ],
)
async def test_the_claim_count_limits_are_inclusive(
    rig: ForecastRig, drafted: list[Claim]
) -> None:
    """Two and four claims are both drafted: the count limits bound inclusively."""
    # Arrange
    rig.drafted = drafted
    rig.writer = ScriptedWriter(analysis_of(drafted))
    if len(drafted) == 4:
        # The default seat ballot votes on two claims; four claims need four votes.
        rig.round_1 = {member: four_vote_ballot() for member in range(1, 8)}
        rig.round_2 = {member: four_vote_ballot() for member in range(1, 8)}
    # Act
    answer = await rig.run()
    # Assert
    for number in range(1, len(drafted) + 1):
        assert f"### Claim {number}:" in answer


@pytest.mark.anyio
async def test_a_hung_drafter_is_a_research_limit_error(
    rig: ForecastRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drafter that never returns ends at the step's own timeout, a 504."""
    # Arrange
    rig.drafted = HANG
    shorten_step(monkeypatch, "draft_claims", SHORT_STEP_SECONDS)
    # Act
    with pytest.raises(ResearchLimitError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 504
    assert "Drafting the claims" in str(raised.value)
    assert rig.member_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("round_1_replies", "member_seconds"),
    [
        pytest.param(
            {5: SEAT_DOWN, 6: SEAT_DOWN, 7: SEAT_DOWN},
            None,
            id="seats are down",
        ),
        pytest.param(
            {
                5: BALLOT_MISSING_A_CLAIM,
                6: BALLOT_MISSING_A_CLAIM,
                7: BALLOT_MISSING_A_CLAIM,
            },
            None,
            id="a ballot misses a claim",
        ),
        pytest.param(
            {
                5: BALLOT_CITING_AN_UNQUOTED_SOURCE,
                6: BALLOT_CITING_AN_UNQUOTED_SOURCE,
                7: BALLOT_CITING_AN_UNQUOTED_SOURCE,
            },
            None,
            id="a vote cites an unquoted source",
        ),
        pytest.param(
            {5: HANG, 6: HANG, 7: HANG},
            SHORT_MEMBER_SECONDS,
            id="seats time out",
        ),
    ],
)
async def test_a_council_below_quorum_stops_before_writing(
    rig: ForecastRig,
    monkeypatch: pytest.MonkeyPatch,
    round_1_replies: dict[int, Any],
    member_seconds: float | None,
) -> None:
    """Round 1 below a quorum of 5 is a 502: no analysis is written."""
    # Arrange
    rig.round_1 = round_1_replies
    if member_seconds is not None:
        shorten_limit(monkeypatch, "council", member_seconds=member_seconds)
    # Act
    with pytest.raises(LLMInvocationError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 502
    assert str(raised.value) == (
        "Only 4 of 7 council members could vote in round 1; the council needs 5."
    )
    assert rig.writer.calls == 0


@pytest.mark.anyio
async def test_exactly_a_quorum_is_enough(rig: ForecastRig) -> None:
    """Five voting seats are the quorum: the forecast stands and reports the count."""
    # Arrange
    rig.round_1 = {6: SEAT_DOWN, 7: SEAT_DOWN}
    # Act
    answer = await rig.run()
    # Assert
    assert "Members voting: 5 of 7 (2 unavailable)." in answer


@pytest.mark.anyio
async def test_a_silent_round_two_keeps_every_round_one_vote(
    rig: ForecastRig,
) -> None:
    """A member with no round-2 ballot keeps its round-1 vote: silence is 'no change'."""
    # Arrange
    rig.round_2 = {member: SEAT_DOWN for member in range(1, 8)}
    # Act
    answer = await rig.run()
    # Assert
    assert (
        "Round 2: 7 of 7 kept their round-1 vote because they did not answer." in answer
    )


@pytest.mark.anyio
async def test_a_hung_writer_is_a_research_limit_error(
    rig: ForecastRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer that never returns ends at the step's own timeout, a 504."""
    # Arrange
    rig.writer = ScriptedWriter(HANG)
    shorten_step(monkeypatch, "write_analysis", SHORT_STEP_SECONDS)
    # Act
    with pytest.raises(ResearchLimitError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 504
    assert "Writing the analysis" in str(raised.value)


@pytest.mark.anyio
async def test_a_crashed_writer_fails_the_forecast(rig: ForecastRig) -> None:
    """A writer that raises is the boundary's 502, never a partial answer."""
    # Arrange
    rig.writer = ScriptedWriter(RuntimeError("bug"))
    # Act
    with pytest.raises(LLMInvocationError) as raised:
        await rig.run()
    # Assert
    assert rig.writer.calls == 1  # a crash, not a retry: the writer ran once
    assert raised.value.status == 502
    assert str(raised.value) == "The forecast failed."


@pytest.mark.anyio
async def test_the_wall_cap_ends_a_real_run(
    rig: ForecastRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run hung past the wall is cancelled and names the step it was in."""
    # Arrange
    rig.writer = ScriptedWriter(HANG)
    shorten_limit(monkeypatch, "graph", wall_seconds=SHORT_WALL_SECONDS)
    # Act
    with pytest.raises(ResearchLimitError) as raised:
        await rig.run()
    # Assert
    assert raised.value.status == 504
    assert str(raised.value).endswith("during this step: Writing the analysis.")
