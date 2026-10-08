"""Unit tests for `agents.deep_forecaster.config`."""

from agents.deep_forecaster.config import LIMITS, RESEARCH_LLM_SETTINGS


def test_the_step_budgets_leave_slack_under_the_wall() -> None:
    # Assert
    assert (
        LIMITS.research_seconds
        + LIMITS.claims_seconds
        + 2 * LIMITS.member_seconds
        + LIMITS.write_seconds
        <= LIMITS.wall_seconds - 30
    )
    assert LIMITS.wall_seconds < 15 * 60


def test_a_free_attempt_leaves_its_fallback_time() -> None:
    # Assert
    assert LIMITS.member_seconds - LIMITS.free_attempt_seconds >= 45


def test_the_research_lead_uses_the_deep_expert_budget() -> None:
    # Assert
    assert RESEARCH_LLM_SETTINGS.model == "gpt-5-mini"
    assert RESEARCH_LLM_SETTINGS.reasoning_effort == "low"
