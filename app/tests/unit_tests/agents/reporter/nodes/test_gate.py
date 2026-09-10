import importlib
import inspect
from typing import Any

import pytest

from agents.reporter.config import MAX_REVISION_ROUNDS
from agents.reporter.consts.messages import CANCELLED_NOTICE

node_module = importlib.import_module("agents.reporter.nodes.gate")


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "transcript": "User: hello",
        "outline": ["First", "Second"],
        "notice": "",
        "instruction": "",
        "revisions": 2,
        "report": "",
    }
    state.update(overrides)
    return state


def _patch_interrupt(monkeypatch: pytest.MonkeyPatch, reply: Any) -> dict[str, Any]:
    received: dict[str, Any] = {}

    def fake_interrupt(value: Any) -> Any:
        received["value"] = value
        return reply

    monkeypatch.setattr(node_module, "interrupt", fake_interrupt)
    return received


@pytest.mark.anyio
async def test_an_approve_decision_keeps_the_revision_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_interrupt(monkeypatch, {"action": "approve"})

    result = await node_module.gate(_state())

    assert result == {"decision": "approve", "instruction": "", "notice": ""}


@pytest.mark.anyio
async def test_a_revise_decision_bumps_revisions_and_carries_the_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_interrupt(monkeypatch, {"action": "revise", "instruction": "drop section 3"})

    result = await node_module.gate(_state(revisions=2))

    assert result == {
        "decision": "revise",
        "instruction": "drop section 3",
        "revisions": 3,
        "notice": "",
    }


@pytest.mark.anyio
async def test_a_cancel_decision_records_the_cancelled_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_interrupt(monkeypatch, {"action": "cancel"})

    result = await node_module.gate(_state())

    assert result["decision"] == "cancel"
    assert result["notice"] == CANCELLED_NOTICE
    assert "revisions" not in result


@pytest.mark.anyio
async def test_a_bare_string_reply_is_decoded_as_a_revise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_interrupt(monkeypatch, "make it shorter")

    result = await node_module.gate(_state(revisions=0))

    assert result["decision"] == "revise"
    assert result["instruction"] == "make it shorter"
    assert result["revisions"] == 1


@pytest.mark.anyio
async def test_the_pause_payload_has_exactly_the_pause_keys_and_a_copied_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(notice="A notice.")
    received = _patch_interrupt(monkeypatch, {"action": "approve"})

    await node_module.gate(state)

    payload = received["value"]
    assert set(payload) == {
        "outline",
        "notice",
        "revisions_used",
        "revisions_allowed",
    }
    assert "kind" not in payload
    assert payload["outline"] == ["First", "Second"]
    assert payload["outline"] is not state["outline"]
    payload["outline"].append("Mutated")
    assert state["outline"] == ["First", "Second"]
    assert payload["notice"] == "A notice."
    assert payload["revisions_used"] == 2
    assert payload["revisions_allowed"] == MAX_REVISION_ROUNDS


def test_gate_takes_no_writer_parameter_because_it_would_refire_on_every_resume() -> (
    None
):
    # Rule 3 of the StreamWriter contract: everything above `interrupt()`
    # re-runs on each resume round, so a writer call in this node would emit
    # again every time the user revises.
    assert "writer" not in inspect.signature(node_module.gate).parameters
