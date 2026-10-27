import pytest

from loadtests.scenarios import Sample
from loadtests.stats import find_breaches, percentile, summarize

TEN_VALUES = [float(value) for value in range(1, 11)]


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        (TEN_VALUES, 50, 5.0),
        (TEN_VALUES, 95, 10.0),
        (TEN_VALUES, 100, 10.0),
        (TEN_VALUES, 1, 1.0),
        ([7.0], 99, 7.0),
    ],
    ids=[
        "median of ten",
        "p95 of ten",
        "p100 is the max",
        "p1 is the min",
        "one value",
    ],
)
def test_percentile_takes_the_nearest_rank(
    values: list[float], q: float, expected: float
) -> None:
    """A nearest-rank percentile is always a latency some request really had,
    never an interpolation between two of them."""
    # Arrange
    # Act
    result = percentile(values, q)

    # Assert
    assert result == expected


def test_percentile_of_no_values_is_an_error() -> None:
    """A run with no samples of a kind has no latency to report; zero would read
    as a fast run."""
    # Arrange
    # Act + Assert
    with pytest.raises(ValueError):
        percentile([], 95)


def test_a_failed_request_counts_as_an_error_and_keeps_its_latency() -> None:
    """A request that failed slowly still kept its user waiting, so it stays in
    the percentiles instead of making the run look faster."""
    # Arrange
    SLOW_FAILURE = 30.0
    samples = [
        Sample("research", ok=True, latency=1.0),
        Sample("research", ok=False, latency=SLOW_FAILURE, error="error frame 504"),
    ]

    # Act
    (summary,) = summarize(samples)

    # Assert
    assert (summary.count, summary.errors, summary.max) == (2, 1, SLOW_FAILURE)
    assert summary.top_errors == (("error frame 504", 1),)


def test_kinds_are_summarized_in_the_order_they_first_appear() -> None:
    """The report reads in the order a user's round sends its requests."""
    # Arrange
    samples = [
        Sample("chat", ok=True, latency=0.1),
        Sample("research", ok=True, latency=2.0),
        Sample("chat", ok=True, latency=0.2),
    ]

    # Act
    summaries = summarize(samples)

    # Assert
    assert [summary.kind for summary in summaries] == ["chat", "research"]


def test_the_first_token_percentile_skips_turns_without_a_token() -> None:
    """A failed turn never streamed a token; counting it as zero would make the
    time to first token look better than any user saw."""
    # Arrange
    FIRST_TOKEN = 0.8
    samples = [
        Sample("chat", ok=True, latency=1.0, first_token=FIRST_TOKEN),
        Sample("chat", ok=False, latency=0.1, error="http 429"),
    ]

    # Act
    (summary,) = summarize(samples)

    # Assert
    assert summary.first_token_p95 == FIRST_TOKEN


@pytest.mark.parametrize(
    ("errors", "expected_breaches"),
    [(0, 0), (1, 0), (2, 1)],
    ids=["no errors", "exactly at the limit", "one past the limit"],
)
def test_an_error_rate_over_the_limit_is_a_breach(
    errors: int, expected_breaches: int
) -> None:
    """The run fails only when a kind's failures exceed the allowed share."""
    # Arrange
    TEN_PERCENT = 0.1
    samples = [
        Sample(
            "chat",
            ok=index >= errors,
            latency=0.1,
            error="" if index >= errors else "http 500",
        )
        for index in range(10)
    ]

    # Act
    breaches = find_breaches(
        summarize(samples), max_error_rate=TEN_PERCENT, max_p95=None
    )

    # Assert
    assert len(breaches) == expected_breaches


def test_a_p95_over_the_limit_names_the_slow_kind() -> None:
    """A latency budget names which request kind blew it, so the report says
    where to look."""
    # Arrange
    BUDGET = 2.0
    samples = [
        Sample("chat", ok=True, latency=0.5),
        Sample("research", ok=True, latency=3.0),
    ]

    # Act
    breaches = find_breaches(summarize(samples), max_error_rate=0.0, max_p95=BUDGET)

    # Assert
    assert breaches == ["research: p95 3.000s over 2.000s"]
