"""Unit tests for `agents.deep_forecaster.nodes.draft_claims`."""

import importlib
from datetime import date
from typing import Any

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from agents.deep_forecaster.consts.forecasters import FORECASTER_SOURCES
from agents.deep_forecaster.models import Claim, EvidenceRef
from models import LLMInvocationError, Source
from unit_tests.agents.deep_forecaster.conftest import (
    TODAY,
    ScriptedDrafter,
    claims,
    sources,
)

draft_module: Any = importlib.import_module("agents.deep_forecaster.nodes.draft_claims")


def _runtime(events: list[dict[str, Any]], today: Any = None) -> Any:
    from types import SimpleNamespace

    from agents.deep_forecaster.state import ForecastRun

    return SimpleNamespace(
        context=ForecastRun(today=today or TODAY), stream_writer=events.append
    )


def _valid_claims() -> list[Claim]:
    return claims()


class TestCheckedClaims:
    def test_accepts_two_to_four_distinct_future_claims(self) -> None:
        checked = draft_module.checked_claims(
            _valid_claims(), today=TODAY, sources=sources()
        )
        assert len(checked) == 2
        assert checked[0].evidence[0].source == 1

    @pytest.mark.parametrize("count", [1, 5])
    def test_the_claim_count_is_enforced(self, count: int) -> None:
        claims_list = [
            Claim(
                statement=f"Claim number {n} is distinct.",
                deadline=date(2027, 1, 1),
                evidence=[EvidenceRef(source=1, paragraph=1)],
            )
            for n in range(1, count + 1)
        ]
        with pytest.raises(LLMInvocationError):
            draft_module.checked_claims(claims_list, today=TODAY, sources=sources())

    def test_two_equal_statements_after_casefold_are_refused(self) -> None:
        claims_list = [
            Claim(
                statement="Alpha happens by 2027.",
                deadline=date(2027, 1, 1),
                evidence=[EvidenceRef(source=1, paragraph=1)],
            ),
            Claim(
                statement="  alpha   happens BY 2027. ",
                deadline=date(2027, 2, 1),
                evidence=[EvidenceRef(source=1, paragraph=1)],
            ),
        ]
        with pytest.raises(LLMInvocationError):
            draft_module.checked_claims(claims_list, today=TODAY, sources=sources())

    @pytest.mark.parametrize(
        "deadline",
        [TODAY, date(2026, 1, 1)],
    )
    def test_the_deadline_must_be_in_the_future(self, deadline: date) -> None:
        claims_list = [
            Claim(
                statement="Alpha happens by 2027.",
                deadline=deadline,
                evidence=[EvidenceRef(source=1, paragraph=1)],
            ),
            Claim(
                statement="Beta happens by 2028.",
                deadline=date(2028, 6, 30),
                evidence=[EvidenceRef(source=1, paragraph=2)],
            ),
        ]
        with pytest.raises(LLMInvocationError, match="not after today"):
            draft_module.checked_claims(claims_list, today=TODAY, sources=sources())

    def test_an_empty_statement_is_refused(self) -> None:
        claims_list = [
            Claim(
                statement="  ",
                deadline=date(2027, 1, 1),
                evidence=[EvidenceRef(source=1, paragraph=1)],
            ),
            Claim(
                statement="Beta happens by 2028.",
                deadline=date(2028, 6, 30),
                evidence=[EvidenceRef(source=1, paragraph=2)],
            ),
        ]
        with pytest.raises(LLMInvocationError):
            draft_module.checked_claims(claims_list, today=TODAY, sources=sources())

    def test_a_claim_with_no_passage_is_refused(self) -> None:
        claims_list = [
            Claim(
                statement="Alpha happens by 2027.",
                deadline=date(2027, 1, 1),
                evidence=[],
            ),
            Claim(
                statement="Beta happens by 2028.",
                deadline=date(2028, 6, 30),
                evidence=[EvidenceRef(source=1, paragraph=2)],
            ),
        ]
        with pytest.raises(LLMInvocationError):
            draft_module.checked_claims(claims_list, today=TODAY, sources=sources())

    def test_a_claim_whose_evidence_all_name_nothing_real_is_refused(self) -> None:
        claims_list = [
            Claim(
                statement="Alpha happens by 2027.",
                deadline=date(2027, 1, 1),
                evidence=[
                    EvidenceRef(source=0, paragraph=1),
                    EvidenceRef(source=3, paragraph=1),
                    EvidenceRef(source=1, paragraph=99),
                ],
            ),
            Claim(
                statement="Beta happens by 2028.",
                deadline=date(2028, 6, 30),
                evidence=[EvidenceRef(source=1, paragraph=2)],
            ),
        ]
        with pytest.raises(LLMInvocationError):
            draft_module.checked_claims(claims_list, today=TODAY, sources=sources())


@pytest.mark.anyio
async def test_evidence_are_tidied_not_refused(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A repeat comes back once; dead numbers drop; at most 6 kept; each tidy logged."""
    # Arrange
    drafted = [
        Claim(
            statement="Alpha happens by 2027.",
            deadline=date(2027, 12, 31),
            evidence=[
                EvidenceRef(source=1, paragraph=1),
                EvidenceRef(source=1, paragraph=1),
            ],
        ),
        Claim(
            statement="Beta happens by 2028.",
            deadline=date(2028, 6, 30),
            evidence=[
                EvidenceRef(source=1, paragraph=1),
                EvidenceRef(source=9, paragraph=1),
                EvidenceRef(source=1, paragraph=99),
            ],
        ),
    ]
    # Act
    checked = draft_module.checked_claims(drafted, today=TODAY, sources=sources())
    # Assert
    assert [ref.paragraph for ref in checked[0].evidence] == [1]
    assert [ref.paragraph for ref in checked[1].evidence] == [1]


@pytest.mark.anyio
async def test_eight_real_evidence_are_cut_to_six(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange
    from agents.deep_forecaster.models import Claim as ClaimModel

    wide = [
        Source("t", "https://carnegieendowment.org/x", "p1\np2\np3\np4\np5\np6\np7\np8")
    ]
    drafted = [
        ClaimModel(
            statement="A claim.",
            deadline=date(2027, 1, 1),
            evidence=[EvidenceRef(source=1, paragraph=n) for n in range(1, 9)],
        ),
        ClaimModel(
            statement="Another claim.",
            deadline=date(2027, 2, 1),
            evidence=[EvidenceRef(source=1, paragraph=1)],
        ),
    ]
    # Act
    checked = draft_module.checked_claims(drafted, today=TODAY, sources=wide)
    # Assert
    assert len(checked[0].evidence) == 6


@pytest.mark.anyio
async def test_the_node_emits_the_claims_label_and_checks(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    from agents.deep_forecaster.consts.progress import CLAIMS_LABEL
    from agents.deep_forecaster.models import DraftedClaims as _Drafted

    drafted = _Drafted(claims=_valid_claims())

    holder: dict[str, Any] = {}

    async def fake_ainvoke(
        prompt: str, messages: Any, schema: Any, *, settings: Any = None
    ) -> Any:
        holder["call"] = (prompt, messages)
        return drafted

    monkeypatch.setattr(draft_module, "ainvoke_structured", fake_ainvoke)
    state = {"question": "q", "sources": sources()}
    # Act
    out = await draft_module.draft_claims(state, _runtime(events))
    # Assert
    assert events[0] == {
        "type": "progress",
        "node": "deep_forecaster",
        "label": CLAIMS_LABEL,
    }
    assert len(out["claims"]) == 2


@pytest.mark.anyio
async def test_the_prompts_carry_today_and_every_number(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    from agents.deep_forecaster.models import DraftedClaims as _Drafted

    drafted = _Drafted(claims=_valid_claims())

    holder: dict[str, Any] = {}

    async def fake_ainvoke(
        prompt: str, messages: Any, schema: Any, *, settings: Any = None
    ) -> Any:
        holder["call"] = (prompt, messages)
        return drafted

    monkeypatch.setattr(draft_module, "ainvoke_structured", fake_ainvoke)
    state = {"question": "q", "sources": sources()}
    # Act
    await draft_module.draft_claims(state, _runtime(events))
    prompt, messages = holder["call"]
    # Assert
    assert isinstance(prompt, str) and "30 September 2026" in prompt
    human = messages[0]
    assert human.content is not None
    text = str(human.content)
    for number in ("[1.1]", "[1.2]", "[1.3]", "[2.1]", "[2.2]", "[2.3]"):
        assert number in text
    assert "https://carnegieendowment.org/a" in text
    assert "https://reuters.com/b" in text


@pytest.mark.anyio
async def test_a_statement_with_a_link_or_a_line_break_is_refused() -> None:
    """A heading-boundary guard: statements render as single plain lines in the view."""
    bad_second = Claim(
        statement="See [x](https://reuters.com/y) today.",
        deadline=date(2027, 1, 1),
        evidence=[EvidenceRef(source=1, paragraph=1)],
    )
    filler = Claim(
        statement="The other claim stands.",
        deadline=date(2028, 1, 1),
        evidence=[EvidenceRef(source=1, paragraph=1)],
    )
    for bad in (
        bad_second,
        Claim(
            statement="Two\nlines.",
            deadline=date(2027, 1, 1),
            evidence=[EvidenceRef(source=1, paragraph=1)],
        ),
    ):
        with pytest.raises(LLMInvocationError, match="link or a line break"):
            draft_module.checked_claims(
                [filler, bad],
                today=TODAY,
                sources=sources(),
            )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("source_len", "expected_first_cut"),
    [
        (FORECASTER_SOURCES.max_source_chars, True),
        (FORECASTER_SOURCES.max_source_chars - 1, False),
    ],
)
async def test_evidence_positions_span_marks_cut_sources(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    captured_spans: InMemorySpanExporter,
    source_len: int,
    expected_first_cut: bool,
) -> None:
    """Source 1 padded to the cap (or one under it) stays 3 paragraphs and is flagged accordingly."""
    # Arrange
    from agents.deep_forecaster.models import DraftedClaims as _Drafted

    def cut_sources() -> list[Source]:
        head = "Alpha one.\nAlpha two.\nAlpha three."
        padding = "\n" * (source_len - len(head))
        padded = head + padding
        assert len(padded) == source_len
        base = sources()
        base[0] = Source(
            base[0].title, base[0].url, padded, author=base[0].author or ""
        )
        return base

    drafted = _Drafted(claims=_valid_claims())

    async def fake_ainvoke(
        prompt: str, messages: Any, schema: Any, *, settings: Any = None
    ) -> Any:
        return drafted

    monkeypatch.setattr(draft_module, "ainvoke_structured", fake_ainvoke)
    state = {"question": "q", "sources": cut_sources()}
    # Act
    await draft_module.draft_claims(state, _runtime(events))
    matches = [
        span
        for span in captured_spans.get_finished_spans()
        if span.name == "evidence_positions" and span.attributes is not None
    ]
    # Assert
    assert len(matches) == 1
    attributes = matches[0].attributes
    assert attributes is not None
    # OTel records sequence attributes as tuples; normalize before comparing.
    positions: tuple[float, ...] = attributes["evidence.positions"]  # type: ignore[assignment]
    cut_flags: tuple[bool, ...] = attributes["evidence.on_cut_source"]  # type: ignore[assignment]
    assert list(positions) == [1 / 3, 2 / 3, 3 / 3]
    # Refs 1 and 3 both read source 1; ref 2 reads source 2, which stays short.
    assert list(cut_flags) == [expected_first_cut, False, expected_first_cut]


PAST_DEADLINE = date(2026, 9, 1)
MARKER = "INJECTED-7f3a"


def _claim(
    statement: str,
    *,
    deadline: date = date(2027, 6, 1),
    evidence: list[EvidenceRef] | None = None,
) -> Claim:
    refs = [EvidenceRef(source=1, paragraph=1)] if evidence is None else evidence
    return Claim(statement=statement, deadline=deadline, evidence=refs)


def _past_deadline_claims() -> list[Claim]:
    """Two claims; the second, which quotes the marker, is due in the past."""
    return [
        _claim("Alpha happens by 2027."),
        _claim(f"Beta {MARKER} happens.", deadline=PAST_DEADLINE),
    ]


def _run_node(monkeypatch: pytest.MonkeyPatch, drafter: ScriptedDrafter) -> Any:
    monkeypatch.setattr(draft_module, "ainvoke_structured", drafter)
    state = {"question": "q", "sources": sources()}
    return draft_module.draft_claims(state, _runtime([]))


@pytest.mark.anyio
async def test_a_past_deadline_is_redrafted_once_with_the_defect_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 2026-10-22 trace lost a whole forecast to one past deadline the drafter could fix."""
    # Arrange
    drafter = ScriptedDrafter(_past_deadline_claims(), claims())
    # Act
    await _run_node(monkeypatch, drafter)
    # Assert
    assert drafter.calls == 2
    assert "An automatic check rejected your previous claims:" in drafter.briefs[1]
    assert "claim 2 with the deadline 2026-09-01" in drafter.briefs[1]


@pytest.mark.anyio
async def test_the_redrafted_claims_are_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node answers with the second draft, not the rejected first."""
    # Arrange
    drafter = ScriptedDrafter(_past_deadline_claims(), claims())
    # Act
    out = await _run_node(monkeypatch, drafter)
    # Assert
    assert [claim.statement for claim in out["claims"]] == [
        "Alpha happens by 2027.",
        "Beta happens by 2028.",
    ]


@pytest.mark.anyio
async def test_a_second_defective_draft_raises_and_makes_no_third_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drafter that repeats its mistake is a hard error, not a loop."""
    # Arrange
    drafter = ScriptedDrafter(_past_deadline_claims(), _past_deadline_claims())
    # Act + Assert
    with pytest.raises(LLMInvocationError, match="claim 2 with the deadline"):
        await _run_node(monkeypatch, drafter)
    assert drafter.calls == 2


@pytest.mark.anyio
async def test_a_first_draft_that_passes_makes_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A good first draft costs nothing extra and carries no retry text."""
    # Arrange
    drafter = ScriptedDrafter(claims())
    # Act
    out = await _run_node(monkeypatch, drafter)
    # Assert
    assert drafter.calls == 1
    assert "automatic check" not in drafter.briefs[0]
    assert len(out["claims"]) == 2


def _five_claims() -> list[Claim]:
    return [_claim(f"Claim number {n} is distinct.") for n in range(1, 6)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_draft",
    [
        [_claim("Only one claim.")],
        _five_claims(),
        [_claim("Alpha happens."), _claim("  ALPHA   happens. ")],
        [_claim("  "), _claim("Beta happens.")],
        [_claim("See [x](https://reuters.com/y)."), _claim("Beta happens.")],
        [_claim("Alpha happens.", evidence=[]), _claim("Beta happens.")],
        [_claim("Alpha happens.", deadline=TODAY), _claim("Beta happens.")],
    ],
    ids=[
        "too few",
        "too many",
        "duplicate",
        "empty",
        "link",
        "no passage",
        "past deadline",
    ],
)
async def test_every_claim_defect_is_redrafted(
    monkeypatch: pytest.MonkeyPatch, bad_draft: list[Claim]
) -> None:
    """Every rule `checked_claims` enforces is one a second draft can fix."""
    # Arrange
    drafter = ScriptedDrafter(bad_draft, claims())
    # Act
    out = await _run_node(monkeypatch, drafter)
    # Assert
    assert drafter.calls == 2
    assert len(out["claims"]) == 2


@pytest.mark.anyio
async def test_a_failed_model_call_is_not_redrafted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure says nothing about the claims; asking again is the model layer's job."""
    # Arrange
    drafter = ScriptedDrafter(LLMInvocationError("provider down"), claims())
    # Act + Assert
    with pytest.raises(LLMInvocationError, match="provider down"):
        await _run_node(monkeypatch, drafter)
    assert drafter.calls == 1


def test_the_deadline_defect_names_the_claim_and_both_dates() -> None:
    """The defect is built from numbers and dates code validated, so it can go to the model."""
    # Arrange
    drafted = _past_deadline_claims()
    # Act + Assert
    with pytest.raises(LLMInvocationError) as raised:
        draft_module.checked_claims(drafted, today=TODAY, sources=sources())
    assert str(raised.value) == (
        "The forecast drafted claim 2 with the deadline 2026-09-01, "
        "which is not after today (2026-09-30)."
    )


@pytest.mark.anyio
async def test_the_redraft_brief_quotes_no_model_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rejected statements are model output; echoing them back would hand a prompt-injected claim a second turn."""
    # Arrange
    drafter = ScriptedDrafter(_past_deadline_claims(), claims())
    # Act
    await _run_node(monkeypatch, drafter)
    # Assert
    assert MARKER in str(_past_deadline_claims()[1].statement)
    assert MARKER not in drafter.briefs[1]


def _span_attributes(captured_spans: InMemorySpanExporter) -> dict[str, Any]:
    spans = [
        span
        for span in captured_spans.get_finished_spans()
        if span.name == "claim_draft"
    ]
    assert len(spans) == 1
    attributes = dict(spans[0].attributes or {})
    return {k: v for k, v in attributes.items() if k.startswith("claims.")}


DEADLINE_DEFECT_1 = (
    "The forecast drafted claim 2 with the deadline 2026-09-01, "
    "which is not after today (2026-09-30)."
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (
            [_past_deadline_claims(), claims()],
            {
                "claims.attempts": 2,
                "claims.first_defect": DEADLINE_DEFECT_1,
                "claims.last_defect": DEADLINE_DEFECT_1,
                "claims.redraft_fixed": True,
                "claims.kept": 2,
            },
        ),
        (
            [claims()],
            {
                "claims.attempts": 1,
                "claims.first_defect": "",
                "claims.last_defect": "",
                "claims.redraft_fixed": False,
                "claims.kept": 2,
            },
        ),
        (
            [
                _past_deadline_claims(),
                [_claim("Only one claim.")],
            ],
            {
                "claims.attempts": 2,
                "claims.first_defect": DEADLINE_DEFECT_1,
                "claims.last_defect": (
                    "The forecast drafted 1 claims; it needs 2 to 4."
                ),
                "claims.redraft_fixed": False,
                "claims.kept": 0,
            },
        ),
    ],
    ids=["redrafted", "first pass", "both defective"],
)
async def test_the_claim_draft_span_records_the_redraft(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    script: list[list[Claim]],
    expected: dict[str, Any],
) -> None:
    """A Phoenix trace alone must say whether the drafter needed its redraft and what it got wrong."""
    # Arrange
    drafter = ScriptedDrafter(*script)
    # Act
    try:
        await _run_node(monkeypatch, drafter)
    except LLMInvocationError:
        pass
    # Assert
    assert _span_attributes(captured_spans) == expected
