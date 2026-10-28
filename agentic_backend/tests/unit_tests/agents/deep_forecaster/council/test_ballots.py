"""Unit tests for `agents.deep_forecaster.council.ballots`."""

from typing import cast

import pytest

from agents.deep_forecaster.config import COUNCIL, LIMITS
from agents.deep_forecaster.council.ballots import (
    count_votes,
    final_ballots,
    round_one_view,
    validate_ballot,
)
from agents.deep_forecaster.models import Ballot, Stance, Vote
from unit_tests.agents.deep_forecaster.conftest import (
    ballot,
)

# What claim 1 and claim 2 quote, per claim: tests give every vote the
# evidence the claims themselves carry (review thread, #142).
QUOTED_BY_CLAIM = {1: frozenset({1, 3}), 2: frozenset({1, 3})}


def _valid() -> Ballot:
    return ballot(["for", "unsure"], evidence={1: [1]})


class TestValidateBallot:
    def test_a_well_formed_ballot_counts(self) -> None:
        assert (
            validate_ballot(_valid(), claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    def test_an_unsure_vote_needs_no_evidence(self) -> None:
        ballot_ = ballot(["unsure", "unsure"], evidence={})
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    @pytest.mark.parametrize(
        "ballot_, why",
        [
            pytest.param(
                ballot(["for"]),
                "it must vote exactly once on each of claims 1 to 2; it voted on 1",
                id="a claim missing",
            ),
            pytest.param(
                ballot(["for", "against", "unsure"]),
                "it must vote exactly once on each of claims 1 to 2; it voted on 1, 2 and 3",
                id="a claim too many",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: []}),
                "claim 1's 'for' vote cites no source",
                id="for without evidence",
            ),
            pytest.param(
                ballot(["against", "unsure"], evidence={1: []}),
                "claim 1's 'against' vote cites no source",
                id="against without evidence",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [2]}),
                "claim 1 cites source 2, which is not among claim 1's passages "
                "(it may cite 1 and 3)",
                id="another claim's source",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [9]}),
                "claim 1 cites source 9, which is not among claim 1's passages "
                "(it may cite 1 and 3)",
                id="a source never quoted",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [1, 3, 2, 3, 2, 1]}),
                "claim 1 cites 6 sources; the limit is 5",
                id="too many sources",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [1, 1, 3, 3]}),
                "claim 1 cites source 1 and 3 more than once",
                id="a repeated source",
            ),
        ],
    )
    def test_refusals(self, ballot_: Ballot, why: str) -> None:
        """A refusal names the claim and the numbers: the member reads it in its
        re-ask, and the operator in the log and on the `council_member` span."""
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) == why
        )

    def test_an_empty_reason(self) -> None:
        ballot_ = Ballot(
            votes=[
                Vote(claim=1, stance="for", reason="   ", evidence=[1]),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
            == "claim 1's reason is empty"
        )

    def test_a_reason_over_the_limit(self) -> None:
        long = "r" * 601
        ballot_ = Ballot(
            votes=[
                Vote(claim=1, stance="for", reason=long, evidence=[1]),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
            == "claim 1's reason is 601 characters; the limit is 600"
        )

    def test_a_reason_carrying_a_url_is_accepted(self) -> None:
        ballot_ = Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance="for",
                    reason="See https://x.example/a.",
                    evidence=[1],
                ),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    def test_a_reason_exactly_at_the_limit_is_accepted(self) -> None:
        """The limit is a limit, not one past it: a reason of exactly
        `max_reason_chars` characters counts (review thread)."""
        # Arrange
        ballot_ = Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance="for",
                    reason="r" * LIMITS.max_reason_chars,
                    evidence=[1],
                ),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        # Act + Assert
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    def test_evidences_exactly_at_the_limit_are_accepted(self) -> None:
        """The limit is a limit, not one past it: exactly `max_evidences`
        distinct sources the claim quotes count (review thread)."""
        # Arrange: claim 1 quotes five sources, so a vote may cite all five.
        all_quoted = {
            1: frozenset({1, 2, 3, 4, 5}),
            2: frozenset({1, 3}),
        }
        ballot_ = Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance="for",
                    reason="ok",
                    evidence=[1, 2, 3, 4, 5],
                ),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        # Act + Assert
        assert validate_ballot(ballot_, claims=2, quoted_by_claim=all_quoted) is None


def _votes_on_one_claim(members: int, stances: list[str]) -> dict[int, Ballot]:
    """`members` ballots; member n votes stances[n-1] on Claim 1."""
    return {
        member: Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance=cast(Stance, stance),
                    reason="r.",
                    evidence=[] if stance == "unsure" else [1],
                )
            ]
        )
        for member, stance in zip(range(1, members + 1), stances, strict=True)
    }


class TestCountVotes:
    def test_five_of_seven_for_is_accepted(self) -> None:
        tally = count_votes(1, _votes_on_one_claim(7, ["for"] * 5 + ["unsure"] * 2))
        assert tally[0].verdict == "ACCEPTED"

    def test_four_of_seven_for_is_unresolved(self) -> None:
        # 4 of 7: threshold ceil(14/3) = 5 → UNRESOLVED
        tally = count_votes(
            1, _votes_on_one_claim(7, ["for"] * 4 + ["against"] + ["unsure"] * 2)
        )
        assert tally[0].verdict == "UNRESOLVED"

    def test_five_of_seven_against_is_rejected(self) -> None:
        tally = count_votes(1, _votes_on_one_claim(7, ["against"] * 5 + ["unsure"] * 2))
        assert tally[0].verdict == "REJECTED"

    def test_four_of_six_for_is_accepted(self) -> None:
        # 6 voting: threshold ceil(12/3) = 4
        tally = count_votes(
            1, _votes_on_one_claim(6, ["for"] * 4 + ["against", "unsure"])
        )
        assert tally[0].verdict == "ACCEPTED"

    def test_three_of_six_for_is_unresolved(self) -> None:
        tally = count_votes(
            1, _votes_on_one_claim(6, ["for"] * 3 + ["against"] * 2 + ["unsure"])
        )
        assert tally[0].verdict == "UNRESOLVED"

    def test_four_of_five_for_is_accepted_and_three_is_not(self) -> None:
        four = count_votes(1, _votes_on_one_claim(5, ["for"] * 4 + ["unsure"]))
        three = count_votes(
            1, _votes_on_one_claim(5, ["for"] * 3 + ["against", "unsure"])
        )
        assert four[0].verdict == "ACCEPTED"
        assert three[0].verdict == "UNRESOLVED"

    def test_the_counts_per_stance_are_right(self) -> None:
        ballots = {
            1: ballot(["for", "unsure"]),
            2: ballot(["against", "for"]),
            3: ballot(["unsure", "unsure"]),
        }
        tally = count_votes(2, ballots)
        assert (
            tally[0].votes_for == 1 and tally[0].against == 1 and tally[0].unsure == 1
        )
        assert tally[0].voting == 3
        assert tally[1].votes_for == 1 and tally[1].unsure == 2


class TestRoundOneView:
    def test_it_shows_everyone_but_the_reader(self) -> None:
        ballots = {member: ballot(["for", "unsure"]) for member in range(1, 5)}
        view = round_one_view(3, ballots)
        assert view.startswith(
            "Round 2. Below are your own round-1 votes, then the other members' "
        )
        assert "Your round-1 votes:" in view
        assert "Member 1:" in view and "Member 2:" in view and "Member 4:" in view
        assert "Member 3:" not in view
        for seat in COUNCIL:
            assert seat.model not in view


class TestFinalBallots:
    def test_each_member_keeps_its_latest_or_first_ballot(self) -> None:
        first = {1: ballot(["for", "unsure"]), 2: ballot(["for", "unsure"])}
        second = {2: ballot(["against", "for"])}
        final = final_ballots(first, second)
        assert final[1] is first[1]
        assert final[2] is second[2]
        assert set(final) == {1, 2}
