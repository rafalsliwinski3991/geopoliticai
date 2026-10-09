"""Unit tests for `agents.deep_forecaster.nodes.draft_claims`."""

import importlib
from datetime import date
from typing import Any

import pytest

from agents.deep_forecaster.models import Claim, EvidenceRef
from models import LLMInvocationError, Source
from unit_tests.agents.deep_forecaster.conftest import TODAY, claims, sources

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
        with pytest.raises(LLMInvocationError):
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
