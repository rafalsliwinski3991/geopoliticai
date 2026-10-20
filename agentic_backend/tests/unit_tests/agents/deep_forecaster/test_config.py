"""Unit tests for `agents.deep_forecaster.config`."""

from agents.deep_forecaster.config import LIMITS, RESEARCH_LLM_SETTINGS


def test_the_step_budgets_leave_slack_under_the_wall() -> None:
    # Assert: research + claims + 2 * member (round 1 and its re-ask)
    # + member (round 2) + write.
    assert (
        LIMITS.research_seconds
        + LIMITS.claims_seconds
        + 3 * LIMITS.member_seconds
        + LIMITS.write_seconds
        <= LIMITS.wall_seconds - 30
    )
    assert LIMITS.wall_seconds < 15 * 60


def test_the_research_lead_uses_the_deep_expert_budget() -> None:
    # Assert
    assert RESEARCH_LLM_SETTINGS.model == "gpt-5-mini"
    assert RESEARCH_LLM_SETTINGS.reasoning_effort == "low"


def test_the_write_call_times_out_with_its_step() -> None:
    from agents.deep_forecaster.config import WRITE_LLM_SETTINGS

    assert WRITE_LLM_SETTINGS.timeout_seconds == LIMITS.write_seconds
    assert WRITE_LLM_SETTINGS.model == "gpt-5-mini"
