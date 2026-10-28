import pytest

from loadtests.run import parse_args


@pytest.mark.parametrize(
    "flags",
    [
        ["--users", "0"],
        ["--rounds", "0"],
        ["--ramp-up", "-1"],
    ],
    ids=["no users", "no rounds", "negative ramp-up"],
)
def test_a_run_that_would_send_nothing_is_refused(flags: list[str]) -> None:
    """Zero users or rounds would pass every limit with no request sent, and a
    negative ramp-up would start users at a negative offset."""
    # Act + Assert
    with pytest.raises(SystemExit):
        parse_args(flags)


def test_a_zero_ramp_up_starts_every_user_at_once() -> None:
    """A burst with no ramp-up is a valid run: the limit is "not negative"."""
    # Arrange
    flags = ["--ramp-up", "0"]

    # Act
    args = parse_args(flags)

    # Assert
    assert args.ramp_up == 0.0
